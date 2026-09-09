"""Batch timing/script evidence and status-aware scores, without count quotas."""
from collections import Counter
import json
import re
from statistics import median

from gold_benchmark import (
    BELOW_NORMAL_DEGRADED_RATIO,
    BELOW_NORMAL_PASS_MAX_RATIO,
    GOLD_BENCHMARK_VERSION,
    HARD_FLOOR_CHARS_PER_LECTURE_MINUTE,
    NEAR_FLOOR_UPPER_CHARS_PER_LECTURE_MINUTE,
    NORMAL_TARGET_MIN_CHARS_PER_LECTURE_MINUTE,
    NORMAL_TARGET_MAX_CHARS_PER_LECTURE_MINUTE,
    script_rate,
)

def planning_profile(content):
    slides=content.get('slides',[])
    chars=[len(re.sub(r'\s+','',s.get('speaker_script',''))) for s in slides]
    rates=[script_rate(n, s['lecture_minutes']) for s,n in zip(slides,chars) if s.get('lecture_minutes',0)>0]
    rates=[rate for rate in rates if rate is not None]
    activity=[s.get('activity_minutes') for s in slides]
    lecture=[s.get('lecture_minutes') for s in slides]
    return {'slide_count':len(slides),'lecture_minutes':lecture,
            'activity_minutes':[s.get('activity_minutes') for s in slides],
            'segment_patterns':[[x.get('minutes') for x in s.get('activity_plan',{}).get('segments',[])] for s in slides],
            'activity_types':[s.get('activity_plan',{}).get('type') for s in slides],
            'layouts':[s.get('layout') for s in slides], 'script_lengths':chars,
            'chars_per_lecture_minute':rates,'median_chars_per_lecture_minute':median(rates) if rates else None,
            'below_normal_ratio':sum(x<NORMAL_TARGET_MIN_CHARS_PER_LECTURE_MINUTE for x in rates)/len(rates) if rates else 0,
            'near_floor_ratio':sum(HARD_FLOOR_CHARS_PER_LECTURE_MINUTE<=x<NEAR_FLOOR_UPPER_CHARS_PER_LECTURE_MINUTE for x in rates)/len(rates) if rates else 0,
            'rich_slide_count':sum(x>=NORMAL_TARGET_MIN_CHARS_PER_LECTURE_MINUTE for x in rates),
            'lecture_activity_ratio':[round(l/(l+a), 4) if isinstance(l, int) and isinstance(a, int) and l+a else None for l,a in zip(lecture, activity)],
            'planning_rationales':[s.get('planning_rationale') for s in slides],
            'coverage_labels':[sorted(s.get('script_coverage', {}).keys()) if isinstance(s.get('script_coverage'), dict) else [] for s in slides]}

def review_batch(contents):
    profiles=[planning_profile(c) for c in contents]
    signals=[]
    if len(profiles)>=3:
        keys=('slide_count','lecture_minutes','activity_minutes','segment_patterns','activity_types','layouts','lecture_activity_ratio')
        repeated=[k for k in keys if len({json.dumps(p[k]) for p in profiles})==1]
        if len(repeated)>=4 and all(p['near_floor_ratio']>0.5 and p['below_normal_ratio']>0.5 for p in profiles):
            signals.append('TEMPLATE_OVERFIT_WARNING: aligned timing/structure and floor-targeted scripts')
        elif len(repeated)>=5 and all(p['below_normal_ratio']>0.75 for p in profiles):
            signals.append('TEMPLATE_OVERFIT_WARNING: correlated planning shape and below-normal script density')
    return {'status':'WARNING' if signals else 'PASS','template_overfit_warning':bool(signals),'warnings':signals,'repeated_dimensions':repeated if len(profiles)>=3 else [],'profiles':profiles}

def coverage_review(content):
    items=[]
    for s in content.get('slides',[]):
        evidence=s.get('script_coverage',{})
        # Excerpts must actually occur in the final script. This is evidence, not a semantic PASS claim.
        valid={k:v for k,v in evidence.items() if isinstance(v,str) and v.strip() and v in s.get('speaker_script','')}
        items.append({'slide_id':s.get('id'),'verified_excerpts':valid,'status':'DEFINED' if len(valid)>=3 else 'REVIEW_REQUIRED'})
    return {'status':'PASS' if all(i['status']=='DEFINED' for i in items) else 'DEGRADED','slides':items}


def _is_gold_core_slide(slide):
    """Exclude cover/index/very-short summary pages from density statistics."""

    if slide.get('delivery_track', 'core') == 'extension':
        return False
    lecture = slide.get('lecture_minutes')
    if not isinstance(lecture, int) or lecture <= 0:
        return False
    title = str(slide.get('title', '')).casefold()
    if lecture <= 2 and re.search(r'(封面|目录|索引|概览|总结|小结|结束|cover|contents|index|overview|summary|recap)', title):
        return False
    script_chars = len(re.sub(r'\s+', '', str(slide.get('speaker_script', ''))))
    if lecture <= 1 and script_chars < 160:
        return False
    return True


def _visual_explanation_item(slide):
    visual_types = {'code', 'table', 'svg', 'image', 'formula', 'comparison'}
    blocks = [block for block in slide.get('blocks', []) if isinstance(block, dict)]
    kinds = [block.get('type') for block in blocks if block.get('type') in visual_types]
    if not kinds:
        return {'slide_id': slide.get('id'), 'required': False, 'status': 'not-required', 'kinds': []}
    coverage = slide.get('script_coverage') if isinstance(slide.get('script_coverage'), dict) else {}
    script = str(slide.get('speaker_script', ''))
    labels = {
        'code': ('code', 'visual_explanation'),
        'table': ('table', 'comparison', 'visual_explanation'),
        'svg': ('svg', 'visual_explanation'),
        'image': ('image', 'visual_explanation'),
        'formula': ('formula', 'visual_explanation'),
        'comparison': ('comparison', 'visual_explanation'),
    }
    covered: list[str] = []
    missing: list[str] = []
    for kind in sorted(set(kinds)):
        excerpts = [coverage.get(label) for label in labels[kind] if isinstance(coverage.get(label), str) and coverage.get(label).strip()]
        if any(excerpt in script for excerpt in excerpts):
            covered.append(kind)
            continue
        # Keep a deterministic fallback for legacy contracts while requiring
        # explicit exact excerpts for the Gold closure prompts.
        normalized = re.sub(r'\s+', '', script)
        markers = {
            'code': ('代码', '逐行', '关键行', '结构'),
            'table': ('表头', '列', '行', '对比'),
            'svg': ('节点', '箭头', '关系', '流程'),
            'image': ('图中', '图示', '观察'),
            'formula': ('公式', '代入', '结果'),
            'comparison': ('比较', '左侧', '右侧'),
        }[kind]
        if any(marker in normalized for marker in markers):
            covered.append(kind)
        else:
            missing.append(kind)
    status = 'PASS' if not missing else 'FAIL'
    return {'slide_id': slide.get('id'), 'required': True, 'status': status, 'kinds': sorted(set(kinds)), 'covered': covered, 'missing': missing}


def gold_batch_review(contents):
    """Run the Courseware-only Gold density/repetition/visual gate."""

    from pedagogical_review import _speaker_script_repetition

    errors = []
    warnings = []
    profiles = []
    for content in contents:
        slides = [slide for slide in content.get('slides', []) if isinstance(slide, dict)]
        core_slides = [slide for slide in slides if _is_gold_core_slide(slide)]
        rates = [
            script_rate(len(re.sub(r'\s+', '', str(slide.get('speaker_script', '')))), slide['lecture_minutes'])
            for slide in core_slides
        ]
        rates = [rate for rate in rates if rate is not None]
        repetition = _speaker_script_repetition(core_slides)
        repetition_metrics = repetition.get('metrics', {})
        visual_items = [_visual_explanation_item(slide) for slide in core_slides]
        required_visuals = [item for item in visual_items if item.get('required')]
        covered_visuals = [item for item in required_visuals if item.get('status') == 'PASS']
        below_ratio = sum(rate < NORMAL_TARGET_MIN_CHARS_PER_LECTURE_MINUTE for rate in rates) / len(rates) if rates else 1.0
        near_floor_ratio = sum(HARD_FLOOR_CHARS_PER_LECTURE_MINUTE <= rate < NEAR_FLOOR_UPPER_CHARS_PER_LECTURE_MINUTE for rate in rates) / len(rates) if rates else 1.0
        profile = {
            'course_title': content.get('course_title'),
            'core_slide_ids': [slide.get('id') for slide in core_slides],
            'excluded_slide_ids': [slide.get('id') for slide in slides if slide not in core_slides],
            'core_slide_count': len(core_slides),
            'chars_per_lecture_minute': [round(rate, 2) for rate in rates],
            'min_chars_per_lecture_minute': round(min(rates), 2) if rates else None,
            'median_chars_per_lecture_minute': round(median(rates), 2) if rates else None,
            'max_chars_per_lecture_minute': round(max(rates), 2) if rates else None,
            'below_normal_ratio': round(below_ratio, 3),
            'near_floor_ratio': round(near_floor_ratio, 3),
            'repeated_ngram_ratio': repetition_metrics.get('repeated_ngram_ratio', 0),
            'repeated_paragraph_count': len(repetition_metrics.get('repeated_paragraphs', [])),
            'visual_explanation_coverage': {
                'required': len(required_visuals),
                'covered': len(covered_visuals),
                'ratio': round(len(covered_visuals) / len(required_visuals), 3) if required_visuals else 1.0,
                'items': visual_items,
            },
        }
        profiles.append(profile)
        prefix = str(content.get('course_title') or 'courseware')
        if not rates:
            errors.append(f'{prefix}: no Gold core slides were eligible for density review')
        if any(rate < HARD_FLOOR_CHARS_PER_LECTURE_MINUTE for rate in rates):
            errors.append(f'{prefix}: at least one Gold core slide is below the hard speaker-script floor')
        if below_ratio >= 0.95:
            errors.append(f'{prefix}: approximately all Gold core slides are below the normal speaker-script target')
        elif below_ratio >= BELOW_NORMAL_PASS_MAX_RATIO:
            warnings.append(f'{prefix}: below-normal speaker-script ratio is {below_ratio:.3f}; normal target generation should be strengthened')
        if near_floor_ratio > BELOW_NORMAL_DEGRADED_RATIO:
            warnings.append(f'{prefix}: near-floor speaker-script ratio is {near_floor_ratio:.3f}')
        if rates and median(rates) < NORMAL_TARGET_MIN_CHARS_PER_LECTURE_MINUTE:
            warnings.append(f'{prefix}: median speaker-script density is below the normal target')
        if repetition.get('status') == 'FAIL':
            errors.extend(f'{prefix}: {error}' for error in repetition.get('errors', []))
        elif repetition.get('warnings'):
            warnings.extend(f'{prefix}: {warning}' for warning in repetition.get('warnings', []))
        if any(item.get('status') == 'FAIL' for item in required_visuals):
            errors.append(f'{prefix}: one or more code/table/SVG/formula explanations lack verifiable script coverage')
    cross_batch = review_batch(contents)
    if cross_batch.get('template_overfit_warning'):
        warnings.extend(cross_batch.get('warnings', []))
    status = 'FAIL' if errors else ('DEGRADED' if warnings else 'PASS')
    return {
        'status': status,
        'benchmark_version': GOLD_BENCHMARK_VERSION,
        'thresholds': {
            'hard_floor_chars_per_lecture_minute': HARD_FLOOR_CHARS_PER_LECTURE_MINUTE,
            'normal_target_chars_per_lecture_minute': [NORMAL_TARGET_MIN_CHARS_PER_LECTURE_MINUTE, NORMAL_TARGET_MAX_CHARS_PER_LECTURE_MINUTE],
            'below_normal_pass_max_ratio': BELOW_NORMAL_PASS_MAX_RATIO,
            'below_normal_degraded_ratio': BELOW_NORMAL_DEGRADED_RATIO,
            'near_floor_upper_chars_per_lecture_minute': NEAR_FLOOR_UPPER_CHARS_PER_LECTURE_MINUTE,
        },
        'errors': errors,
        'warnings': warnings,
        'profiles': profiles,
        'cross_batch': cross_batch,
    }

def automatic_scores(gates, pedagogical):
    dimensions=('contract','reference_behavior','package_integrity','source_formula_truth','time_evidence','browser')
    def normal(value):
        return str(value or 'NOT_RUN').upper().replace('-', '_')
    objective={k:5 if normal(gates.get(k))=='PASS' else (3 if normal(gates.get(k)) in {'MANUAL_EVIDENCE_DEFINED','AUTOMATED_UNAVAILABLE'} else 0) for k in dimensions}
    statuses=[normal(p.get('status','NOT_RUN')) for p in pedagogical]
    score=30 if statuses and all(s=='PASS' for s in statuses) else (24 if statuses and all(s in {'PASS','DEGRADED'} for s in statuses) else 0)
    return {'objective':sum(objective.values()),'objective_max':30,'objective_dimensions':objective,'pedagogical':score,'pedagogical_max':30,'pedagogical_subsystems':statuses,'human':'PENDING','human_max':40}
