"""
Frozen V3 production pipeline.

Generated from the evaluated notebook implementation using
the dependency closure of run_stage5_pipeline_v2.

Notebook examples, smoke tests and evaluation executions are
excluded. Model, retrieval, routing and synthesis logic remains
frozen after the final holdout.
"""
from pathlib import Path
import re
import numpy as np
import pandas as pd
from rank_bm25 import BM25Okapi
from sentence_transformers import SentenceTransformer
PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROCESSED_DIR = PROJECT_ROOT / 'data' / 'processed'
RETRIEVAL_DIR = PROJECT_ROOT / 'data' / 'retrieval'
TRIALS_PATH = PROCESSED_DIR / 'obesity_development_core_stage5_semantics.parquet'
CHUNKS_PATH = RETRIEVAL_DIR / 'retrieval_chunks.parquet'
EMBEDDINGS_PATH = RETRIEVAL_DIR / 'bge_base_en_v1_5_chunk_embeddings.npy'
MODEL_NAME = 'BAAI/bge-base-en-v1.5'
QUERY_PREFIX = 'Represent this sentence for searching relevant passages: '
RRF_K = 60
ACTIVE_STATUSES = {'RECRUITING', 'ACTIVE_NOT_RECRUITING', 'NOT_YET_RECRUITING', 'ENROLLING_BY_INVITATION'}
trials = pd.read_parquet(TRIALS_PATH)
chunks = pd.read_parquet(CHUNKS_PATH)
LIST_COLUMNS = ['phases', 'conditions', 'keywords', 'intervention_names', 'intervention_types', 'intervention_descriptions', 'primary_outcomes', 'secondary_outcomes', 'countries', 'states', 'cities', 'canonical_interventions', 'normalized_programs', 'owned_programs', 'intervention_mentions']

def parse_list(x):
    """
    Normalize list-valued fields loaded from Parquet.

    Notebook execution held these values as Python lists,
    while pyarrow/pandas may reload them as numpy.ndarray.
    """
    if x is None:
        return []
    if isinstance(x, np.ndarray):
        x = x.tolist()
    if isinstance(x, (tuple, set)):
        x = list(x)
    if isinstance(x, list):
        out = []

        def flatten(value):
            if isinstance(value, np.ndarray):
                flatten(value.tolist())
            elif isinstance(value, (list, tuple, set)):
                for item in value:
                    flatten(item)
            elif value is None:
                return
            else:
                try:
                    if pd.isna(value):
                        return
                except (TypeError, ValueError):
                    pass
                out.append(value)
        flatten(x)
        return out
    if isinstance(x, str):
        try:
            parsed = json.loads(x)
            if isinstance(parsed, np.ndarray):
                parsed = parsed.tolist()
            if isinstance(parsed, list):
                return parse_list(parsed)
        except Exception:
            pass
    return []
for col in LIST_COLUMNS:
    if col in trials.columns:
        trials[col] = trials[col].apply(parse_list)
trials['start_date'] = pd.to_datetime(trials['start_date'], errors='coerce')
trials['start_year'] = trials['start_date'].dt.year
trials['is_active'] = trials['overall_status'].isin(ACTIVE_STATUSES)
TOKEN_PATTERN = re.compile('[a-z0-9]+(?:-[a-z0-9]+)*')

def tokenize(text):
    return TOKEN_PATTERN.findall(str(text).lower())
tokenized_corpus = chunks['content'].fillna('').apply(tokenize).tolist()
bm25 = BM25Okapi(tokenized_corpus)
dense_model = SentenceTransformer(MODEL_NAME)
chunk_embeddings = np.load(EMBEDDINGS_PATH)
SEARCH_COLUMNS = ['chunk_id', 'nct_id', 'chunk_type', 'canonical_company', 'brief_title', 'content']

def bm25_trial_ranking(query):
    scores = bm25.get_scores(tokenize(query))
    result = chunks[SEARCH_COLUMNS].copy()
    result['bm25_score'] = scores
    result = result.sort_values(['bm25_score', 'chunk_id'], ascending=[False, True]).drop_duplicates('nct_id').reset_index(drop=True)
    result['bm25_rank'] = np.arange(len(result)) + 1
    return result

def dense_trial_ranking(query):
    query_embedding = dense_model.encode([QUERY_PREFIX + str(query)], normalize_embeddings=True, convert_to_numpy=True)[0]
    scores = chunk_embeddings @ query_embedding
    result = chunks[SEARCH_COLUMNS].copy()
    result['dense_score'] = scores
    result = result.sort_values(['dense_score', 'chunk_id'], ascending=[False, True]).drop_duplicates('nct_id').reset_index(drop=True)
    result['dense_rank'] = np.arange(len(result)) + 1
    return result

def search_trial_evidence(query, top_k=10):
    bm25_results = bm25_trial_ranking(query)
    dense_results = dense_trial_ranking(query)
    bm25_side = bm25_results[['nct_id', 'bm25_rank', 'bm25_score', 'chunk_id', 'chunk_type', 'content', 'canonical_company', 'brief_title']].rename(columns={'chunk_id': 'bm25_chunk_id', 'chunk_type': 'bm25_chunk_type', 'content': 'bm25_content'})
    dense_side = dense_results[['nct_id', 'dense_rank', 'dense_score', 'chunk_id', 'chunk_type', 'content']].rename(columns={'chunk_id': 'dense_chunk_id', 'chunk_type': 'dense_chunk_type', 'content': 'dense_content'})
    fused = bm25_side.merge(dense_side, on='nct_id', how='inner', validate='one_to_one')
    fused['rrf_score'] = 1.0 / (RRF_K + fused['bm25_rank']) + 1.0 / (RRF_K + fused['dense_rank'])
    fused = fused.sort_values(['rrf_score', 'bm25_rank', 'dense_rank'], ascending=[False, True, True]).head(top_k).reset_index(drop=True)
    fused['rank'] = np.arange(len(fused)) + 1
    fused['evidence_content'] = np.where(fused['bm25_rank'] <= fused['dense_rank'], fused['bm25_content'], fused['dense_content'])
    fused['evidence_chunk_id'] = np.where(fused['bm25_rank'] <= fused['dense_rank'], fused['bm25_chunk_id'], fused['dense_chunk_id'])
    return fused[['rank', 'nct_id', 'canonical_company', 'brief_title', 'rrf_score', 'bm25_rank', 'dense_rank', 'evidence_chunk_id', 'evidence_content']].to_dict(orient='records')

def get_owned_programs(row):
    company = row['canonical_company']
    mentions = row['normalized_programs']
    if not isinstance(mentions, list):
        return []
    return [program for program in mentions if PROGRAM_OWNER_MAP.get(program) == company]
import boto3
from botocore.config import Config
AWS_REGION = 'us-east-1'
PLANNER_MODEL_ID = 'us.amazon.nova-2-lite-v1:0'
PLANNER_MAX_TOKENS = 1200
PLANNER_TEMPERATURE = 0.0
bedrock = boto3.client('bedrock-runtime', region_name=AWS_REGION, config=Config(read_timeout=120, connect_timeout=20, retries={'max_attempts': 3, 'mode': 'standard'}))
from dataclasses import dataclass, field, asdict
from typing import Optional, Literal
import json
PROGRAM_OWNER_MAP = {'Semaglutide': 'Novo Nordisk', 'Liraglutide': 'Novo Nordisk', 'Cagrilintide': 'Novo Nordisk', 'CagriSema': 'Novo Nordisk', 'Zenagamtide': 'Novo Nordisk', 'NNC0662-0419': 'Novo Nordisk', 'Tirzepatide': 'Eli Lilly', 'Retatrutide': 'Eli Lilly', 'Eloralintide': 'Eli Lilly', 'Orforglipron': 'Eli Lilly', 'Bimagrumab': 'Eli Lilly', 'Macupatide': 'Eli Lilly', 'Naperiglipron': 'Eli Lilly', 'Survodutide': 'Boehringer Ingelheim', 'Maridebart cafraglutide': 'Amgen'}
PRIMARY_PROGRAM_PATTERNS = {'CagriSema': ['cagrisema'], 'Maridebart cafraglutide': ['maridebart cafraglutide'], 'Survodutide': ['survodutide', 'bi 456906', 'bi456906'], 'Retatrutide': ['retatrutide', 'ly3437943'], 'Orforglipron': ['orforglipron', 'ly3502970'], 'Eloralintide': ['eloralintide', 'ly3841136'], 'Macupatide': ['macupatide', 'ly3532226'], 'Naperiglipron': ['naperiglipron', 'ly3549492'], 'Tirzepatide': ['tirzepatide', 'ly3298176'], 'Bimagrumab': ['bimagrumab'], 'Zenagamtide': ['zenagamtide', 'nnc0487-0111'], 'NNC0662-0419': ['nnc0662-0419'], 'Cagrilintide': ['cagrilintide'], 'Semaglutide': ['semaglutide'], 'Liraglutide': ['liraglutide']}
PROGRAM_PRIORITY = list(PRIMARY_PROGRAM_PATTERNS.keys())

def ensure_list(value):
    if isinstance(value, list):
        return value
    if value is None:
        return []
    try:
        if pd.isna(value):
            return []
    except Exception:
        pass
    return [value]

def program_mentioned(text, program):
    text = str(text or '').lower()
    aliases = PRIMARY_PROGRAM_PATTERNS[program]
    return any((alias.lower() in text for alias in aliases))

def derive_primary_program(row):
    company = row['canonical_company']
    title = str(row.get('brief_title', '') or '')
    interventions = ensure_list(row.get('intervention_names', []))
    intervention_text = ' | '.join((str(x) for x in interventions))
    owned = list(dict.fromkeys(ensure_list(row.get('owned_programs', []))))
    title_matches = []
    for program in PROGRAM_PRIORITY:
        if PROGRAM_OWNER_MAP.get(program) == company and program_mentioned(title, program):
            title_matches.append(program)
    if 'CagriSema' in title_matches:
        return 'CagriSema'
    if len(title_matches) == 1:
        return title_matches[0]
    if company == 'Novo Nordisk' and program_mentioned(intervention_text, 'CagriSema'):
        return 'CagriSema'
    if len(owned) == 1:
        return owned[0]
    owned_title_matches = [program for program in owned if program in PRIMARY_PROGRAM_PATTERNS and program_mentioned(title, program)]
    owned_title_matches = list(dict.fromkeys(owned_title_matches))
    if 'CagriSema' in owned_title_matches:
        return 'CagriSema'
    if len(owned_title_matches) == 1:
        return owned_title_matches[0]
    owned_intervention_matches = [program for program in owned if program in PRIMARY_PROGRAM_PATTERNS and program_mentioned(intervention_text, program)]
    owned_intervention_matches = list(dict.fromkeys(owned_intervention_matches))
    if 'CagriSema' in owned_intervention_matches:
        return 'CagriSema'
    if len(owned_intervention_matches) == 1:
        return owned_intervention_matches[0]
    return None
Route = Literal['structured', 'retrieval', 'hybrid', 'abstain']
StructuredOperation = Literal['filter_trials', 'summarize_trials', 'get_trial']

@dataclass
class TrialFilters:
    companies: list[str] = field(default_factory=list)
    primary_programs: list[str] = field(default_factory=list)
    owned_programs: list[str] = field(default_factory=list)
    intervention_mentions: list[str] = field(default_factory=list)
    phases: list[str] = field(default_factory=list)
    statuses: list[str] = field(default_factory=list)
    active_only: Optional[bool] = None
    start_year_min: Optional[int] = None
    start_year_max: Optional[int] = None
    nct_ids: list[str] = field(default_factory=list)

@dataclass
class QueryPlan:
    route: Route
    structured_operation: Optional[StructuredOperation] = None
    filters: TrialFilters = field(default_factory=TrialFilters)
    retrieval_query: Optional[str] = None
    retrieval_top_k: int = 10
    nct_id: Optional[str] = None
    reason: Optional[str] = None

def query_trials(companies=None, primary_programs=None, owned_programs=None, intervention_mentions=None, phases=None, statuses=None, active_only=None, start_year_min=None, start_year_max=None, nct_ids=None):
    df = trials.copy()
    if companies:
        df = df.loc[df['canonical_company'].isin(set(companies))]
    if primary_programs:
        df = df.loc[df['primary_program'].isin(set(primary_programs))]
    if owned_programs:
        targets = set(owned_programs)
        df = df.loc[df['owned_programs'].apply(lambda xs: bool(targets & set(ensure_list(xs))))]
    if intervention_mentions:
        targets = set(intervention_mentions)
        df = df.loc[df['intervention_mentions'].apply(lambda xs: bool(targets & set(ensure_list(xs))))]
    if phases:
        targets = set(phases)
        df = df.loc[df['phases'].apply(lambda xs: bool(targets & set(ensure_list(xs))))]
    if statuses:
        df = df.loc[df['overall_status'].isin(set(statuses))]
    if active_only is True:
        df = df.loc[df['is_active']]
    elif active_only is False:
        df = df.loc[~df['is_active']]
    if start_year_min is not None:
        df = df.loc[df['start_year'] >= start_year_min]
    if start_year_max is not None:
        df = df.loc[df['start_year'] <= start_year_max]
    if nct_ids:
        df = df.loc[df['nct_id'].isin(set(nct_ids))]
    return df.copy().reset_index(drop=True)

def get_trial(nct_id):
    rows = trials.loc[trials['nct_id'] == nct_id]
    if rows.empty:
        return None
    row = rows.iloc[0]
    start_date = row['start_date']
    return {'nct_id': row['nct_id'], 'company': row['canonical_company'], 'primary_program': row['primary_program'], 'owned_programs': row['owned_programs'], 'intervention_mentions': row['intervention_mentions'], 'phases': row['phases'], 'status': row['overall_status'], 'title': row['brief_title'], 'conditions': row['conditions'], 'start_date': start_date.date().isoformat() if pd.notna(start_date) else None, 'enrollment': float(row['enrollment']) if pd.notna(row['enrollment']) else None, 'countries': row['countries'], 'primary_outcomes': row['primary_outcomes'], 'secondary_outcomes': row['secondary_outcomes'], 'brief_summary': row['brief_summary']}

def has_retrieval_scope(filters):
    return any([bool(filters.companies), bool(filters.primary_programs), bool(filters.owned_programs), bool(filters.intervention_mentions), bool(filters.phases), bool(filters.statuses), filters.active_only is not None, filters.start_year_min is not None, filters.start_year_max is not None, bool(filters.nct_ids)])

def get_eligible_nct_ids(filters):
    df = query_trials(companies=filters.companies or None, primary_programs=filters.primary_programs or None, owned_programs=filters.owned_programs or None, intervention_mentions=filters.intervention_mentions or None, phases=filters.phases or None, statuses=filters.statuses or None, active_only=filters.active_only, start_year_min=filters.start_year_min, start_year_max=filters.start_year_max, nct_ids=filters.nct_ids or None)
    return set(df['nct_id'].astype(str).tolist())

def search_trial_evidence_scoped(query, top_k=10, filters=None):
    if filters is None:
        filters = TrialFilters()
    if not has_retrieval_scope(filters):
        return search_trial_evidence(query=query, top_k=top_k)
    eligible = get_eligible_nct_ids(filters)
    if not eligible:
        return []
    full_k = int(trials['nct_id'].nunique())
    ranked = search_trial_evidence(query=query, top_k=full_k)
    scoped = [item for item in ranked if str(item['nct_id']) in eligible][:top_k]
    output = []
    for rank, item in enumerate(scoped, start=1):
        result = dict(item)
        result['global_rank'] = item.get('rank')
        result['rank'] = rank
        output.append(result)
    return output

def execute_query_plan(plan):
    validate_query_plan(plan)
    output = {'route': plan.route, 'plan': asdict(plan), 'structured_result': None, 'retrieval_result': None, 'retrieval_scope': None, 'abstained': False}
    if plan.route == 'abstain':
        output['abstained'] = True
        return output
    if plan.route in {'structured', 'hybrid'}:
        output['structured_result'] = execute_structured_tool(plan)
    if plan.route in {'retrieval', 'hybrid'}:
        eligible = get_eligible_nct_ids(plan.filters) if has_retrieval_scope(plan.filters) else set(trials['nct_id'].astype(str))
        output['retrieval_scope'] = {'scoped': has_retrieval_scope(plan.filters), 'eligible_trial_count': len(eligible), 'filters': asdict(plan.filters)}
        output['retrieval_result'] = search_trial_evidence_scoped(query=plan.retrieval_query, top_k=plan.retrieval_top_k, filters=plan.filters)
    return output
ALLOWED_COMPANIES = ['Novo Nordisk', 'Eli Lilly', 'Amgen', 'Boehringer Ingelheim']
ALLOWED_PRIMARY_PROGRAMS = sorted(trials['primary_program'].dropna().unique().tolist())
ALLOWED_OWNED_PROGRAMS = sorted(PROGRAM_OWNER_MAP.keys())
ALLOWED_INTERVENTION_MENTIONS = sorted(trials['intervention_mentions'].explode().dropna().astype(str).unique().tolist())
ALLOWED_PHASES = ['PHASE2', 'PHASE3']
ALLOWED_STATUSES = sorted(trials['overall_status'].dropna().unique().tolist())
QUERY_PLAN_TOOL_SCHEMA = {'type': 'object', 'properties': {'route': {'type': 'string', 'enum': ['structured', 'retrieval', 'hybrid', 'abstain']}, 'structured_operation': {'type': ['string', 'null'], 'enum': ['filter_trials', 'summarize_trials', 'get_trial', None]}, 'filters': {'type': 'object', 'properties': {'companies': {'type': 'array', 'items': {'type': 'string'}}, 'primary_programs': {'type': 'array', 'items': {'type': 'string'}}, 'owned_programs': {'type': 'array', 'items': {'type': 'string'}}, 'intervention_mentions': {'type': 'array', 'items': {'type': 'string'}}, 'phases': {'type': 'array', 'items': {'type': 'string'}}, 'statuses': {'type': 'array', 'items': {'type': 'string'}}, 'active_only': {'type': ['boolean', 'null']}, 'start_year_min': {'type': ['integer', 'null']}, 'start_year_max': {'type': ['integer', 'null']}, 'nct_ids': {'type': 'array', 'items': {'type': 'string'}}}, 'required': ['companies', 'primary_programs', 'owned_programs', 'intervention_mentions', 'phases', 'statuses', 'active_only', 'start_year_min', 'start_year_max', 'nct_ids']}, 'retrieval_query': {'type': ['string', 'null']}, 'retrieval_top_k': {'type': 'integer'}, 'nct_id': {'type': ['string', 'null']}, 'reason': {'type': 'string'}}, 'required': ['route', 'structured_operation', 'filters', 'retrieval_query', 'retrieval_top_k', 'nct_id', 'reason']}
PLANNER_TOOL_CONFIG = {'tools': [{'toolSpec': {'name': 'emit_query_plan', 'description': 'Return the execution plan only.', 'inputSchema': {'json': QUERY_PLAN_TOOL_SCHEMA}}}], 'toolChoice': {'tool': {'name': 'emit_query_plan'}}}
PLANNER_SYSTEM_PROMPT = f'\nYou are the query planner for an obesity clinical-trial\ncompetitive-intelligence system.\n\nDo NOT answer the question.\n\nCall emit_query_plan exactly once.\n\nSUPPORTED COMPANIES:\n{json.dumps(ALLOWED_COMPANIES)}\n\nPRIMARY DEVELOPMENT PROGRAMS:\n{json.dumps(ALLOWED_PRIMARY_PROGRAMS)}\n\nROUTES:\n\nstructured:\ndeterministic counts, filters, distributions, listings and exact\ntrial lookup.\n\nretrieval:\nnarrative evidence such as populations, objectives, outcomes and\nclinical contexts.\n\nhybrid:\nboth deterministic aggregation and narrative evidence.\n\nabstain:\ninformation outside the trial corpus such as market share,\nrevenue, stock forecasts, medical advice or future approval\nprobability.\n\n\nFILTER SEMANTICS:\n\nprimary_programs:\nDEFAULT for named development-program questions.\n\nExamples:\n"Semaglutide development program"\n-> primary_programs=["Semaglutide"]\n\n"Compare Tirzepatide and Semaglutide programs"\n-> primary_programs=["Tirzepatide","Semaglutide"]\n\n\nowned_programs:\nbroader sponsor-owned asset/component participation.\nUse only if the question explicitly concerns participation of the\nasset/component rather than canonical development-program identity.\n\n\nintervention_mentions:\nany trial mentioning the intervention, including external comparator\nuse.\n\n\nCRITICAL:\nCagriSema is its own primary development program.\nA CagriSema trial may contain Semaglutide and Cagrilintide, but it\nmust NOT be counted as a primary Semaglutide development-program\ntrial.\n\nUse summarize_trials for counts/comparisons.\nUse filter_trials for listing matching trials.\nUse get_trial for an exact NCT ID.\n\nProgram-level questions should use primary_programs.\n\nDo not duplicate the same drug across primary_programs,\nowned_programs or intervention_mentions.\n\nretrieval_top_k should normally be 10.\n\nFor structured-only:\nretrieval_query=null.\n\nFor retrieval-only:\nstructured_operation=null.\n\nFor hybrid:\nboth are required.\n\nFor abstain:\nboth are null.\n\nKeep reason concise.\n'.strip()

def dict_to_query_plan(data):
    f = data.get('filters', {}) or {}
    return QueryPlan(route=data['route'], structured_operation=data.get('structured_operation'), filters=TrialFilters(companies=f.get('companies') or [], primary_programs=f.get('primary_programs') or [], owned_programs=f.get('owned_programs') or [], intervention_mentions=f.get('intervention_mentions') or [], phases=f.get('phases') or [], statuses=f.get('statuses') or [], active_only=f.get('active_only'), start_year_min=f.get('start_year_min'), start_year_max=f.get('start_year_max'), nct_ids=f.get('nct_ids') or []), retrieval_query=data.get('retrieval_query'), retrieval_top_k=data.get('retrieval_top_k', 10), nct_id=data.get('nct_id'), reason=data.get('reason'))

def validate_planner_semantics(plan):
    validate_query_plan(plan)
    checks = [('companies', plan.filters.companies, ALLOWED_COMPANIES), ('primary_programs', plan.filters.primary_programs, ALLOWED_PRIMARY_PROGRAMS), ('owned_programs', plan.filters.owned_programs, ALLOWED_OWNED_PROGRAMS), ('intervention_mentions', plan.filters.intervention_mentions, ALLOWED_INTERVENTION_MENTIONS), ('phases', plan.filters.phases, ALLOWED_PHASES), ('statuses', plan.filters.statuses, ALLOWED_STATUSES)]
    errors = []
    for name, values, allowed in checks:
        unknown = set(values) - set(allowed)
        if unknown:
            errors.append(f'Unknown {name}: {sorted(unknown)}')
    if plan.filters.companies and plan.filters.primary_programs:
        companies = set(plan.filters.companies)
        for program in plan.filters.primary_programs:
            owner = PROGRAM_OWNER_MAP.get(program)
            if owner and owner not in companies:
                errors.append(f'{program} belongs to {owner}, which is absent from company filter.')
    if errors:
        raise ValueError('\n'.join(errors))
    return True

def plan_question(question):
    start = time.perf_counter()
    response = bedrock.converse(modelId=PLANNER_MODEL_ID, system=[{'text': PLANNER_SYSTEM_PROMPT}], messages=[{'role': 'user', 'content': [{'text': question}]}], toolConfig=PLANNER_TOOL_CONFIG, inferenceConfig={'maxTokens': PLANNER_MAX_TOKENS, 'temperature': PLANNER_TEMPERATURE})
    latency_ms = (time.perf_counter() - start) * 1000
    content = response['output']['message']['content']
    tool_calls = [block['toolUse'] for block in content if 'toolUse' in block and block['toolUse'].get('name') == 'emit_query_plan']
    if len(tool_calls) != 1:
        raise RuntimeError('Expected one emit_query_plan call.')
    raw_plan = tool_calls[0]['input']
    plan = dict_to_query_plan(raw_plan)
    validate_planner_semantics(plan)
    usage = response.get('usage', {})
    metadata = {'model_id': PLANNER_MODEL_ID, 'latency_ms': round(latency_ms, 1), 'input_tokens': usage.get('inputTokens'), 'output_tokens': usage.get('outputTokens'), 'total_tokens': usage.get('totalTokens')}
    return (plan, metadata, raw_plan)
PRIMARY_PROGRAM_OVERRIDES = {'NCT06662383': 'Retatrutide', 'NCT04074161': 'Semaglutide', 'NCT07400107': 'Zenagamtide', 'NCT07668414': 'Zenagamtide', 'NCT04969939': None}
MULTI_PROGRAM_TRIALS = {'NCT06143956', 'NCT06603571', 'NCT06643728', 'NCT06901349'}
for nct_id, primary in PRIMARY_PROGRAM_OVERRIDES.items():
    mask = trials['nct_id'] == nct_id
    assert mask.sum() == 1, f'{nct_id} not uniquely present.'
    trials.loc[mask, 'primary_program'] = primary
for nct_id in MULTI_PROGRAM_TRIALS:
    mask = trials['nct_id'] == nct_id
    assert mask.sum() == 1
    trials.loc[mask, 'primary_program'] = None

def determine_program_assignment_type(row):
    nct_id = row['nct_id']
    if nct_id in MULTI_PROGRAM_TRIALS:
        return 'multi_program'
    if pd.isna(row['primary_program']):
        return 'unresolved_or_combination'
    return 'single_primary'

def rebuild_owned_programs(row):
    company = row['canonical_company']
    mentions = ensure_list(row['intervention_mentions'])
    owned = [program for program in mentions if PROGRAM_OWNER_MAP.get(program) == company]
    primary = row['primary_program']
    if pd.notna(primary) and PROGRAM_OWNER_MAP.get(primary) == company:
        owned.append(primary)
    return list(dict.fromkeys(owned))

def default_support_type_for_route(route):
    if route == 'structured':
        return 'structured'
    if route == 'retrieval':
        return 'evidence'
    if route == 'hybrid':
        return 'mixed'
    return 'structured'

def normalize_citations(value):
    if value is None:
        return []
    if isinstance(value, str):
        return list(dict.fromkeys(NCT_PATTERN.findall(value)))
    if isinstance(value, list):
        normalized = []
        for item in value:
            if isinstance(item, str):
                found = NCT_PATTERN.findall(item)
                if found:
                    normalized.extend(found)
        return list(dict.fromkeys(normalized))
    return []

def normalize_grounded_answer(answer_object, route):
    if not isinstance(answer_object, dict):
        answer_object = {'answer': str(answer_object), 'key_findings': [], 'limitations': []}
    normalized_answer = normalize_claim(answer_object.get('answer', ''), route=route)
    raw_findings = answer_object.get('key_findings', [])
    if not isinstance(raw_findings, list):
        raw_findings = [raw_findings]
    normalized_findings = [normalize_claim(finding, route=route) for finding in raw_findings]
    raw_limitations = answer_object.get('limitations', [])
    if raw_limitations is None:
        raw_limitations = []
    if isinstance(raw_limitations, str):
        raw_limitations = [raw_limitations]
    limitations = [str(limitation).strip() for limitation in raw_limitations if str(limitation).strip()]
    return {'answer': normalized_answer, 'key_findings': normalized_findings, 'limitations': limitations}

def validate_claim(claim, allowed_citations, claim_name):
    errors = []
    if not isinstance(claim, dict):
        return ([f'{claim_name}: claim is not an object.'], [])
    text = str(claim.get('text', '')).strip()
    support_type = claim.get('support_type')
    citations = normalize_citations(claim.get('citations', []))
    if not text:
        errors.append(f'{claim_name}: claim text is empty.')
    if support_type not in {'structured', 'evidence', 'mixed'}:
        errors.append(f'{claim_name}: invalid support_type {support_type!r}.')
    if support_type == 'structured' and citations:
        errors.append(f'{claim_name}: structured claim must have citations=[].')
    if support_type in {'evidence', 'mixed'} and (not citations):
        errors.append(f'{claim_name}: {support_type} claim requires at least one retrieved citation.')
    invalid_citations = set(citations) - set(allowed_citations)
    if invalid_citations:
        errors.append(f'{claim_name}: citation IDs were not present in retrieved evidence: {sorted(invalid_citations)}')
    inline_ncts = set(NCT_PATTERN.findall(text))
    undeclared_inline = inline_ncts - set(citations)
    if undeclared_inline:
        errors.append(f'{claim_name}: inline NCT IDs not declared as citations: {sorted(undeclared_inline)}')
    return (errors, citations)

def validate_grounded_answer(answer_object, payload, route):
    errors = []
    allowed_citations = set(payload.get('ALLOWED_NARRATIVE_CITATION_IDS', []))
    normalized = normalize_grounded_answer(answer_object=answer_object, route=route)
    used_citations = []
    claim_errors, citations = validate_claim(claim=normalized.get('answer', {}), allowed_citations=allowed_citations, claim_name='answer')
    errors.extend(claim_errors)
    used_citations.extend(citations)
    findings = normalized.get('key_findings', []) or []
    for index, finding in enumerate(findings, start=1):
        claim_errors, citations = validate_claim(claim=finding, allowed_citations=allowed_citations, claim_name=f'key_findings[{index}]')
        errors.extend(claim_errors)
        used_citations.extend(citations)
    limitations = normalized.get('limitations', []) or []
    invalid_limitations = [limitation for limitation in limitations if limitation not in SYSTEM_LIMITATIONS]
    if invalid_limitations:
        errors.append(f'Unsupported limitations generated: {invalid_limitations}')
    if route in {'retrieval', 'hybrid'} and allowed_citations and (not used_citations):
        errors.append('Retrieval/hybrid answer did not cite any retrieved evidence.')
    all_claims = [normalized.get('answer', {})] + list(findings)
    evidence_claims = [claim for claim in all_claims if claim.get('support_type') in {'evidence', 'mixed'}]
    cited_evidence_claims = [claim for claim in evidence_claims if claim.get('citations')]
    citation_coverage = len(cited_evidence_claims) / len(evidence_claims) if evidence_claims else None
    if errors:
        raise ValueError('\n'.join(errors))
    return (normalized, {'valid': True, 'allowed_citations': sorted(allowed_citations), 'used_citations': sorted(set(used_citations)), 'citation_validity': 1.0, 'citation_coverage': citation_coverage, 'semantic_entailment_evaluated': False})
import time

class AnswerContractError(RuntimeError):
    pass

def extract_answer_tool_payload(response):
    content = response['output']['message']['content']
    tool_calls = [block['toolUse'] for block in content if 'toolUse' in block and block['toolUse'].get('name') == 'emit_grounded_answer']
    if len(tool_calls) != 1:
        raise AnswerContractError(f'Expected exactly one emit_grounded_answer tool call; received {len(tool_calls)}.')
    return tool_calls[0]['input']

def response_metadata(response, latency_ms):
    usage = response.get('usage', {}) or {}
    return {'latency_ms': round(latency_ms, 1), 'input_tokens': usage.get('inputTokens'), 'output_tokens': usage.get('outputTokens'), 'total_tokens': usage.get('totalTokens'), 'stop_reason': response.get('stopReason')}

def call_initial_synthesis(question, plan, execution):
    payload = build_synthesis_payload(question=question, plan=plan, execution=execution)
    start = time.perf_counter()
    response = bedrock.converse(modelId=SYNTHESIS_MODEL_ID, system=[{'text': SYNTHESIS_SYSTEM_PROMPT}], messages=[{'role': 'user', 'content': [{'text': json.dumps(payload, indent=2, default=str)}]}], toolConfig=ANSWER_TOOL_CONFIG, inferenceConfig={'maxTokens': SYNTHESIS_MAX_TOKENS, 'temperature': SYNTHESIS_TEMPERATURE})
    latency_ms = (time.perf_counter() - start) * 1000
    raw_answer = extract_answer_tool_payload(response)
    metadata = response_metadata(response, latency_ms)
    return (raw_answer, metadata, payload)
REPAIR_SYSTEM_PROMPT = '\nYou are repairing the STRUCTURE of a previously generated\nevidence-grounded pharmaceutical competitive-intelligence answer.\n\nThe previous output failed deterministic validation.\n\nYou MUST regenerate the complete final answer from the supplied\ntrusted analytical context.\n\nDo not merely patch the malformed JSON.\nRe-read the supplied context and emit a fresh answer.\n\nMANDATORY CONTRACT:\n\nanswer:\n{\n  "text": non-empty string,\n  "support_type": "structured" | "evidence" | "mixed",\n  "citations": []\n}\n\nkey_findings:\nlist of objects using exactly the same three fields.\n\nlimitations:\nlist containing ONLY exact strings from ALLOWED_LIMITATIONS.\n\n\nSUPPORT RULES:\n\nstructured:\n- deterministic counts/distributions only\n- citations MUST be []\n\nevidence:\n- narrative claims based on retrieved trials\n- citations MUST contain retrieved NCT IDs\n\nmixed:\n- combines deterministic facts and narrative evidence\n- citations MUST support the narrative portion\n\n\nCRITICAL:\n\nFor retrieval and hybrid questions:\n- the top-level answer must contain meaningful text\n- narrative content must have citations\n- use only NCT IDs in ALLOWED_NARRATIVE_CITATION_IDS\n\nFor structured questions:\n- do not invent citations\n\nDo not use external knowledge.\nDo not fabricate NCT IDs.\nDo not invent limitations.\nDo not state registry objectives as observed clinical outcomes.\n'.strip()

def call_repair_synthesis(payload, raw_answer, validation_error):
    repair_input = {'VALIDATION_FAILURE': str(validation_error), 'PREVIOUS_MALFORMED_OUTPUT': make_json_safe(raw_answer), 'TRUSTED_ANALYTICAL_CONTEXT': payload}
    start = time.perf_counter()
    response = bedrock.converse(modelId=SYNTHESIS_MODEL_ID, system=[{'text': REPAIR_SYSTEM_PROMPT}], messages=[{'role': 'user', 'content': [{'text': json.dumps(repair_input, indent=2, default=str)}]}], toolConfig=ANSWER_TOOL_CONFIG, inferenceConfig={'maxTokens': SYNTHESIS_MAX_TOKENS, 'temperature': 0.0})
    latency_ms = (time.perf_counter() - start) * 1000
    repaired_answer = extract_answer_tool_payload(response)
    metadata = response_metadata(response, latency_ms)
    return (repaired_answer, metadata)

def synthesize_and_validate_stage5(question, plan, execution):
    raw_answer, attempt1_meta, payload = call_initial_synthesis(question=question, plan=plan, execution=execution)
    try:
        normalized_answer, validation = validate_grounded_answer(answer_object=raw_answer, payload=payload, route=plan.route)
        return {'answer': normalized_answer, 'validation': validation, 'raw_answer_attempt_1': raw_answer, 'raw_answer_attempt_2': None, 'payload': payload, 'metadata': {'repaired': False, 'attempt_count': 1, 'attempt_1': attempt1_meta, 'attempt_2': None, 'total_synthesis_latency_ms': attempt1_meta['latency_ms'], 'total_synthesis_input_tokens': attempt1_meta.get('input_tokens'), 'total_synthesis_output_tokens': attempt1_meta.get('output_tokens'), 'total_synthesis_tokens': attempt1_meta.get('total_tokens')}}
    except ValueError as first_error:
        repaired_raw_answer, attempt2_meta = call_repair_synthesis(payload=payload, raw_answer=raw_answer, validation_error=first_error)
        try:
            normalized_answer, validation = validate_grounded_answer(answer_object=repaired_raw_answer, payload=payload, route=plan.route)
        except ValueError as second_error:
            raise AnswerContractError(f'\nANSWER CONTRACT FAILED AFTER REPAIR.\n\nFIRST VALIDATION ERROR:\n{first_error}\n\nSECOND VALIDATION ERROR:\n{second_error}\n\nATTEMPT 1 RAW OUTPUT:\n' + json.dumps(raw_answer, indent=2, default=str) + '\n\nATTEMPT 2 RAW OUTPUT:\n' + json.dumps(repaired_raw_answer, indent=2, default=str))

        def safe_sum(a, b):
            values = [x for x in [a, b] if x is not None]
            return sum(values) if values else None
        return {'answer': normalized_answer, 'validation': validation, 'raw_answer_attempt_1': raw_answer, 'raw_answer_attempt_2': repaired_raw_answer, 'payload': payload, 'metadata': {'repaired': True, 'attempt_count': 2, 'first_validation_error': str(first_error), 'attempt_1': attempt1_meta, 'attempt_2': attempt2_meta, 'total_synthesis_latency_ms': safe_sum(attempt1_meta.get('latency_ms'), attempt2_meta.get('latency_ms')), 'total_synthesis_input_tokens': safe_sum(attempt1_meta.get('input_tokens'), attempt2_meta.get('input_tokens')), 'total_synthesis_output_tokens': safe_sum(attempt1_meta.get('output_tokens'), attempt2_meta.get('output_tokens')), 'total_synthesis_tokens': safe_sum(attempt1_meta.get('total_tokens'), attempt2_meta.get('total_tokens'))}}

def run_stage5_pipeline_v2(question):
    total_start = time.perf_counter()
    plan, planner_metadata, raw_plan = plan_question(question)
    execution = execute_query_plan(plan)
    if plan.route == 'abstain':
        answer = normalize_grounded_answer(answer_object=build_abstention_answer(plan), route=plan.route)
        synthesis_metadata = None
        grounding_validation = {'valid': True, 'allowed_citations': [], 'used_citations': [], 'citation_validity': None, 'citation_coverage': None, 'semantic_entailment_evaluated': False}
        raw_attempt_1 = None
        raw_attempt_2 = None
        evidence_payload = None
    else:
        synthesis_result = synthesize_and_validate_stage5(question=question, plan=plan, execution=execution)
        answer = synthesis_result['answer']
        grounding_validation = synthesis_result['validation']
        synthesis_metadata = synthesis_result['metadata']
        raw_attempt_1 = synthesis_result['raw_answer_attempt_1']
        raw_attempt_2 = synthesis_result['raw_answer_attempt_2']
        evidence_payload = synthesis_result['payload']
    total_latency_ms = (time.perf_counter() - total_start) * 1000
    result = {'question': question, 'plan': asdict(plan), 'raw_plan': raw_plan, 'execution': execution, 'answer': answer, 'grounding_validation': grounding_validation, 'raw_synthesis_answer_attempt_1': raw_attempt_1, 'raw_synthesis_answer_attempt_2': raw_attempt_2, 'evidence_payload': evidence_payload, 'metadata': {'planner': planner_metadata, 'synthesis': synthesis_metadata, 'total_latency_ms': round(total_latency_ms, 1)}}
    required = {'question', 'plan', 'execution', 'answer', 'grounding_validation', 'metadata'}
    missing = required - set(result.keys())
    if missing:
        raise RuntimeError(f'Invalid Stage-5 pipeline response. Missing: {sorted(missing)}')
    return result

def list_value_counts(df, column):
    if df.empty or column not in df.columns:
        return {}
    exploded = df[['nct_id', column]].explode(column).dropna(subset=[column])
    if exploded.empty:
        return {}
    return exploded[column].value_counts().to_dict()

def country_summary(df, top_n=10):
    if df.empty or 'countries' not in df.columns:
        return {'unique_countries': 0, 'top_countries': {}}
    country_counts = df[['nct_id', 'countries']].explode('countries').dropna(subset=['countries'])['countries'].value_counts()
    return {'unique_countries': int(len(country_counts)), 'top_countries': country_counts.head(top_n).to_dict()}

def enrollment_summary(df):
    if df.empty or 'enrollment' not in df.columns:
        return {'median': None, 'mean': None, 'min': None, 'max': None}
    enrollment = pd.to_numeric(df['enrollment'], errors='coerce').replace(0, np.nan).dropna()
    if enrollment.empty:
        return {'median': None, 'mean': None, 'min': None, 'max': None}
    return {'median': float(enrollment.median()), 'mean': float(enrollment.mean()), 'min': float(enrollment.min()), 'max': float(enrollment.max())}

def start_year_summary(df):
    if df.empty or 'start_year' not in df.columns:
        return {'min': None, 'max': None}
    years = pd.to_numeric(df['start_year'], errors='coerce').dropna()
    if years.empty:
        return {'min': None, 'max': None}
    return {'min': int(years.min()), 'max': int(years.max())}

def grouped_breakdown(df, group_column):
    if df.empty or group_column not in df.columns:
        return {}
    working = df.loc[df[group_column].notna()].copy()
    breakdown = {}
    for group_value, group_df in working.groupby(group_column, sort=True):
        breakdown[str(group_value)] = summarize_group(group_df)
    return breakdown

def summarize_trials(companies=None, primary_programs=None, owned_programs=None, intervention_mentions=None, phases=None, statuses=None, active_only=None, start_year_min=None, start_year_max=None):
    df = query_trials(companies=companies, primary_programs=primary_programs, owned_programs=owned_programs, intervention_mentions=intervention_mentions, phases=phases, statuses=statuses, active_only=active_only, start_year_min=start_year_min, start_year_max=start_year_max)
    trial_count = int(len(df))
    if trial_count == 0:
        return {'trial_count': 0, 'active_trial_count': 0, 'active_share': None, 'companies': {}, 'primary_programs': {}, 'phases': {}, 'statuses': {}, 'owned_programs': {}, 'intervention_mentions': {}, 'start_year_range': {'min': None, 'max': None}, 'enrollment': {'median': None, 'mean': None, 'min': None, 'max': None}, 'unique_countries': 0, 'top_countries': {}, 'company_breakdown': {}, 'primary_program_breakdown': {}}
    active_count = int(df['is_active'].fillna(False).sum())
    geography = country_summary(df)
    result = {'trial_count': trial_count, 'active_trial_count': active_count, 'active_share': active_count / trial_count, 'companies': df['canonical_company'].value_counts().to_dict(), 'primary_programs': df['primary_program'].dropna().value_counts().to_dict(), 'phases': list_value_counts(df, 'phases'), 'statuses': df['overall_status'].value_counts().to_dict(), 'owned_programs': list_value_counts(df, 'owned_programs'), 'intervention_mentions': list_value_counts(df, 'intervention_mentions'), 'start_year_range': start_year_summary(df), 'enrollment': enrollment_summary(df), 'unique_countries': geography['unique_countries'], 'top_countries': geography['top_countries'], 'company_breakdown': grouped_breakdown(df, 'canonical_company'), 'primary_program_breakdown': grouped_breakdown(df, 'primary_program')}
    return result

def execute_structured_tool(plan):
    f = plan.filters
    if plan.structured_operation == 'get_trial':
        return get_trial(plan.nct_id)
    kwargs = {'companies': f.companies or None, 'primary_programs': f.primary_programs or None, 'owned_programs': f.owned_programs or None, 'intervention_mentions': f.intervention_mentions or None, 'phases': f.phases or None, 'statuses': f.statuses or None, 'active_only': f.active_only, 'start_year_min': f.start_year_min, 'start_year_max': f.start_year_max}
    if plan.structured_operation == 'summarize_trials':
        return summarize_trials(**kwargs)
    if plan.structured_operation == 'filter_trials':
        df = query_trials(**kwargs, nct_ids=f.nct_ids or None)
        columns = ['nct_id', 'canonical_company', 'primary_program', 'owned_programs', 'intervention_mentions', 'phases', 'overall_status', 'start_date', 'enrollment', 'countries', 'brief_title']
        output = df[columns].copy()
        output['start_date'] = output['start_date'].apply(lambda x: x.date().isoformat() if pd.notna(x) else None)
        return output.to_dict(orient='records')
    raise ValueError('Unknown structured operation.')
import re
from dataclasses import asdict
PHASE_ALIAS_MAP = {'phase 1': 'PHASE1', 'phase1': 'PHASE1', 'phase i': 'PHASE1', 'phase 2': 'PHASE2', 'phase2': 'PHASE2', 'phase ii': 'PHASE2', 'phase 2/3': 'PHASE2|PHASE3', 'phase2/3': 'PHASE2|PHASE3', 'phase 2-3': 'PHASE2|PHASE3', 'phase 3': 'PHASE3', 'phase3': 'PHASE3', 'phase iii': 'PHASE3', 'phase 3b': 'PHASE3', 'phase3b': 'PHASE3', 'phase 4': 'PHASE4', 'phase4': 'PHASE4', 'early phase 1': 'EARLY_PHASE1', 'n/a': 'NA', 'na': 'NA'}
VALID_CANONICAL_PHASES = {'EARLY_PHASE1', 'PHASE1', 'PHASE2', 'PHASE3', 'PHASE4', 'NA'}

def canonicalize_phase_values(values):
    if not values:
        return []
    output = []
    for value in values:
        raw = str(value).strip()
        normalized_key = raw.lower()
        mapped = PHASE_ALIAS_MAP.get(normalized_key, raw.upper())
        if mapped == 'PHASE2|PHASE3':
            for phase in ['PHASE2', 'PHASE3']:
                if phase not in output:
                    output.append(phase)
            continue
        mapped = mapped.replace(' ', '_').replace('-', '_')
        if mapped == 'PHASE_1':
            mapped = 'PHASE1'
        elif mapped == 'PHASE_2':
            mapped = 'PHASE2'
        elif mapped == 'PHASE_3':
            mapped = 'PHASE3'
        elif mapped == 'PHASE_4':
            mapped = 'PHASE4'
        if mapped not in output:
            output.append(mapped)
    return output
STATUS_ALIAS_MAP = {'not yet recruiting': 'NOT_YET_RECRUITING', 'not_yet_recruiting': 'NOT_YET_RECRUITING', 'recruiting': 'RECRUITING', 'enrolling by invitation': 'ENROLLING_BY_INVITATION', 'active, not recruiting': 'ACTIVE_NOT_RECRUITING', 'active not recruiting': 'ACTIVE_NOT_RECRUITING', 'active_not_recruiting': 'ACTIVE_NOT_RECRUITING', 'suspended': 'SUSPENDED', 'terminated': 'TERMINATED', 'completed': 'COMPLETED', 'withdrawn': 'WITHDRAWN', 'unknown': 'UNKNOWN'}
VALID_CANONICAL_STATUSES = {'NOT_YET_RECRUITING', 'RECRUITING', 'ENROLLING_BY_INVITATION', 'ACTIVE_NOT_RECRUITING', 'SUSPENDED', 'TERMINATED', 'COMPLETED', 'WITHDRAWN', 'UNKNOWN'}
ACTIVE_STATUS_ALIASES = {'active', 'currently active', 'ongoing', 'open'}

def canonicalize_status_values(values, current_active_only=None):
    if not values:
        return ([], current_active_only)
    output = []
    active_only = current_active_only
    for value in values:
        raw = str(value).strip()
        normalized_key = raw.lower()
        if normalized_key in ACTIVE_STATUS_ALIASES:
            active_only = True
            continue
        mapped = STATUS_ALIAS_MAP.get(normalized_key)
        if mapped is None:
            mapped = raw.upper().replace(' ', '_').replace(',', '').replace('-', '_')
        if mapped not in output:
            output.append(mapped)
    return (output, active_only)

def normalize_query_plan_v2(plan):
    plan.filters.phases = canonicalize_phase_values(plan.filters.phases)
    normalized_statuses, normalized_active_only = canonicalize_status_values(plan.filters.statuses, plan.filters.active_only)
    plan.filters.statuses = normalized_statuses
    plan.filters.active_only = normalized_active_only
    if plan.filters.primary_programs:
        owners = {PROGRAM_OWNER_MAP[program] for program in plan.filters.primary_programs if program in PROGRAM_OWNER_MAP}
        if owners:
            plan.filters.companies = sorted(owners)
    if plan.structured_operation == 'get_trial':
        plan.filters = TrialFilters()
    if plan.route not in {'retrieval', 'hybrid'}:
        plan.retrieval_top_k = 10
    return plan

def validate_query_plan(plan):
    normalize_query_plan_v2(plan)
    errors = []
    if plan.route == 'structured':
        if plan.structured_operation is None:
            errors.append('Structured route requires structured_operation.')
        if plan.retrieval_query is not None:
            errors.append('Structured route cannot contain retrieval_query.')
    elif plan.route == 'retrieval':
        if not plan.retrieval_query:
            errors.append('Retrieval route requires retrieval_query.')
        if plan.structured_operation is not None:
            errors.append('Retrieval route cannot contain structured_operation.')
    elif plan.route == 'hybrid':
        if plan.structured_operation is None:
            errors.append('Hybrid route requires structured_operation.')
        if not plan.retrieval_query:
            errors.append('Hybrid route requires retrieval_query.')
    elif plan.route == 'abstain':
        if plan.structured_operation is not None:
            errors.append('Abstain route cannot contain structured_operation.')
        if plan.retrieval_query is not None:
            errors.append('Abstain route cannot contain retrieval_query.')
    else:
        errors.append(f'Unknown route: {plan.route}')
    if plan.route in {'retrieval', 'hybrid'}:
        if not (isinstance(plan.retrieval_top_k, int) and 1 <= plan.retrieval_top_k <= 20):
            errors.append('retrieval_top_k must be between 1 and 20 for retrieval/hybrid routes.')
    unknown_phases = [phase for phase in plan.filters.phases if phase not in VALID_CANONICAL_PHASES]
    if unknown_phases:
        errors.append(f'Unknown phases: {unknown_phases}')
    unknown_statuses = [status for status in plan.filters.statuses if status not in VALID_CANONICAL_STATUSES]
    if unknown_statuses:
        errors.append(f'Unknown statuses: {unknown_statuses}')
    if plan.structured_operation == 'get_trial':
        if not plan.nct_id:
            errors.append('get_trial requires nct_id.')
    elif plan.nct_id is not None:
        errors.append('nct_id is only valid for get_trial.')
    semantic_sets = {'primary_programs': set(plan.filters.primary_programs), 'owned_programs': set(plan.filters.owned_programs), 'intervention_mentions': set(plan.filters.intervention_mentions)}
    for left, right in [('primary_programs', 'owned_programs'), ('primary_programs', 'intervention_mentions'), ('owned_programs', 'intervention_mentions')]:
        overlap = semantic_sets[left] & semantic_sets[right]
        if overlap:
            errors.append(f'Same asset appears in {left} and {right}: {sorted(overlap)}')
    if errors:
        raise ValueError('\n'.join(errors))
    return True
SUPERIORITY_PATTERNS = ['\\bclinically superior\\b', '\\bprove\\b.*\\bsuperior\\b', '\\bguarantee\\b.*\\bsuperior\\b', '\\bdefinitively\\b.*\\bbetter\\b', '\\bprove\\b.*\\bbetter\\b']

def requires_deterministic_abstention(question):
    text = str(question).lower()
    for pattern in SUPERIORITY_PATTERNS:
        if re.search(pattern, text):
            return True
    return False
_plan_question_before_v2 = plan_question

def plan_question(question):
    plan, metadata, raw_plan = _plan_question_before_v2(question)
    if requires_deterministic_abstention(question):
        plan.route = 'abstain'
        plan.structured_operation = None
        plan.filters = TrialFilters()
        plan.retrieval_query = None
        plan.retrieval_top_k = 10
        plan.nct_id = None
        plan.reason = 'The request asks the system to establish clinical superiority from registry-level cross-trial evidence, which the system does not support.'
    normalize_query_plan_v2(plan)
    validate_query_plan(plan)
    return (plan, metadata, raw_plan)
NCT_PATTERN = re.compile('\\bNCT\\d{8}\\b')

def normalize_claim(claim, route):
    if isinstance(claim, str):
        text = claim.strip()
        inline = list(dict.fromkeys(NCT_PATTERN.findall(text)))
        if inline:
            support_type = 'evidence' if route == 'retrieval' else 'mixed'
        else:
            support_type = default_support_type_for_route(route)
        return {'text': text, 'support_type': support_type, 'citations': inline}
    if not isinstance(claim, dict):
        return {'text': '', 'support_type': default_support_type_for_route(route), 'citations': []}
    text = claim.get('text') or claim.get('finding') or claim.get('answer') or ''
    text = str(text).strip()
    citations = normalize_citations(claim.get('citations'))
    inline_ids = list(dict.fromkeys(NCT_PATTERN.findall(text)))
    for nct_id in inline_ids:
        if nct_id not in citations:
            citations.append(nct_id)
    support_type = claim.get('support_type')
    if support_type not in {'structured', 'evidence', 'mixed'}:
        support_type = default_support_type_for_route(route)
    if support_type == 'structured' and citations:
        support_type = 'mixed'
    return {'text': text, 'support_type': support_type, 'citations': citations}
import re
ACTIVE_RATIO_PATTERNS = ['\\bactive share\\b', '\\bshare of .*active\\b', '\\bproportion of .*active\\b', '\\bpercentage of .*active\\b', '\\bpercent of .*active\\b', '\\brate of .*active\\b', '\\bactive proportion\\b', '\\bactive percentage\\b']

def asks_for_active_ratio(question):
    text = str(question).strip().lower()
    return any((re.search(pattern, text) for pattern in ACTIVE_RATIO_PATTERNS))

def enforce_company_program_consistency(plan):
    companies = set(plan.filters.companies or [])
    programs = list(plan.filters.primary_programs or [])
    if not programs:
        return plan
    if companies:
        compatible_programs = []
        for program in programs:
            owner = PROGRAM_OWNER_MAP.get(program)
            if owner is None or owner in companies:
                compatible_programs.append(program)
        plan.filters.primary_programs = compatible_programs
    else:
        owners = sorted({PROGRAM_OWNER_MAP[program] for program in programs if program in PROGRAM_OWNER_MAP})
        if owners:
            plan.filters.companies = owners
    return plan

def normalize_plan_for_question(question, plan):
    plan.filters.phases = canonicalize_phase_values(plan.filters.phases)
    statuses, active_only = canonicalize_status_values(plan.filters.statuses, plan.filters.active_only)
    plan.filters.statuses = statuses
    plan.filters.active_only = active_only
    if asks_for_active_ratio(question):
        plan.filters.active_only = None
    enforce_company_program_consistency(plan)
    if plan.route not in {'retrieval', 'hybrid'}:
        plan.retrieval_top_k = 10
    return plan
_plan_question_v2_frozen = plan_question

def plan_question(question):
    plan, metadata, raw_plan = _plan_question_v2_frozen(question)
    if requires_deterministic_abstention(question):
        plan.route = 'abstain'
        plan.structured_operation = None
        plan.filters = TrialFilters()
        plan.retrieval_query = None
        plan.retrieval_top_k = 10
        plan.nct_id = None
        plan.reason = 'The request asks the system to establish clinical superiority from registry-level cross-trial evidence, which the system does not support.'
    normalize_plan_for_question(question, plan)
    validate_query_plan(plan)
    return (plan, metadata, raw_plan)

def status_share_dict(df):
    if df.empty:
        return {}
    counts = df['overall_status'].value_counts()
    total = int(len(df))
    return {status: float(count / total) for status, count in counts.items()}

def summarize_group(df):
    trial_count = int(len(df))
    if trial_count == 0:
        return {'trial_count': 0, 'active_trial_count': 0, 'active_share': None, 'phases': {}, 'statuses': {}, 'status_shares': {}, 'enrollment': enrollment_summary(df), 'start_year_range': start_year_summary(df), 'unique_countries': 0, 'top_countries': {}}
    active_count = int(df['is_active'].fillna(False).sum())
    geography = country_summary(df)
    return {'trial_count': trial_count, 'active_trial_count': active_count, 'active_share': float(active_count / trial_count), 'phases': list_value_counts(df, 'phases'), 'statuses': df['overall_status'].value_counts().to_dict(), 'status_shares': status_share_dict(df), 'enrollment': enrollment_summary(df), 'start_year_range': start_year_summary(df), 'unique_countries': geography['unique_countries'], 'top_countries': geography['top_countries']}
import json
import numpy as np
import pandas as pd
