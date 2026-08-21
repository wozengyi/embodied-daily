"""Rewrite build_daily.py with wider coverage, 7d arXiv rolling window, persistent history."""
import os, re, sys, json, time, ssl, urllib.request, urllib.parse, urllib.error
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
import argparse

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / 'data'
HISTORY_PATH = DATA_DIR / 'history.json'
OUT_PATH = DATA_DIR / 'daily.json'
LATEST_PATH = DATA_DIR / 'latest.json'
BOOTSTRAP_PATH = DATA_DIR / 'data.js'
SEARCH_INDEX_PATH = DATA_DIR / 'search-index.json'

UA = 'Mozilla/5.0 (EmbodiedDaily/1.1; +https://github.com/)'
CTX = ssl.create_default_context()

# ---- Keyword rules (wider set) ----
EMBODIMENT_KW_BROAD = [
    'embodied', 'embodied ai', 'embodied agent',
    'robot', 'robotic', 'robotics', 'robot learning',
    'manipulation', 'manipulator', 'manipulat',
    'grasp', 'grasping', 'dexter',
    'humanoid', 'whole-body', 'whole body control', 'anthropomorphic',
    'locomotion', 'legged', 'biped', 'quadruped', 'gait',
    'navigation', 'pointnav', 'objectnav', 'visual navigation', 'slam',
    'teleoperation', 'tele-op', 'teleop', 'vr control',
    'bimanual', 'dual-arm', 'aloha',
    'mobile manipulation',
    'deformable object', 'deformable-object', 'soft object', 'soft-object', 'cloth manipulation',
    'tactile', 'tactile manipulation', 'visuo-tactile', 'visuotactile', 'tactile dataset',
    'sim2real', 'sim-to-real', 'domain randomization',
    'vla', 'vision-language-action', 'vision language action', 'vision-language policy',
    'diffusion policy', 'behavior cloning', 'imitation learning', 'learning from demonstration',
    'world model for robot', 'video world model', 'world action model', 'world-action model',
    'rl for robot', 'reinforcement learning robot',
    'affordance', 'motion planning',
    'huggingface',
    # Platforms / labs / well-known systems (important for recall)
    'unitree', 'boston dynamics', 'atlas', 'spot', 'figure 0', 'figure-0', 'optimus',
    '1x ', 'physical intelligence', 'pi0', 'π0',
    'shadow hand', 'allegro hand', 'barrett hand', 'wam', 'whole-arm manipulator',
    'franka', 'panda', 'kuka', 'ur5', 'ur10', 'sawyer', 'baxter', 'fetch robot',
    'aloha', 'droid dataset', 'bridge data', 'open x-embodiment',
    'rt-1', 'rt-2', 'rt-3', 'octo', 'openvla',
    'robot foundation model', 'generalist robot policy', 'generalist robot',
    'habitat', 'isaac lab', 'isaac sim', 'mani skill', 'robosuite', 'mujoco',
]
STRONG_KWS = [
    'robot','robotic','robotics','embodied','manipulat','grasp','humanoid','locomotion','navigation',
    'teleop','dexter','bimanual','legged','vla','sim2real','unitree','allegro','shadow hand','barrett',
    'franka','panda','kuka','aloha','mujoco','habitat','isaac','robosuite','dexterous',
    'tactile','visuo-tactile','visuotactile','deformable','soft object','physical intelligence',
    'robot foundation model','generalist robot'
]

TOPIC_RULES = [
    ('VLA', [r'\bvla\b', r'vision[- ]language[- ]action', r'vision.language.action',
             r'vision[- ]language[- ]to[- ]action', r'vision[- ]language[- ]policy',
             r'rt-?\d\b', r'robotics transformer', r'openvla', r'\bocto\b', r'pi_?0', r'π_?0',
             r'vision[- ]language[- ]model.*(policy|robot|control|action|manipulation)',
             r'language[- ]conditioned (policy|control|manipulation|action)',
             r'language[- ]guided (policy|control|manipulation)']),
        ('Manipulation', [r'robotic manipulation', r'manipulation (task|policy|skill|dataset|benchmark|of|for|with|robot|objects|object|scene|grasp|dexterous|bimanual)', r'deformable[- ]object', r'soft[- ]object', r'cloth manipulation', r'visuo[- ]tactile.*manipulat', r'pick[- ]and[- ]place', r'robotic arm', r'contact-rich', r'whole-arm', r'\bwam\b', r'object manipulation', r'manipulator (arm|control|kinematic)']),
    ('Grasping', [r'\bgrasp(ing|er)?\b', r'6-?dof grasp', r'graspnet', r'anygrasp']),
    ('Humanoid', [r'humanoid', r'whole[- ]body control', r'anthropomorphic',
                  r'figure[- ]?0\d?', r'optimus', r'\b1x\b', r'unitree g\d', r'\batlas\b']),
    ('Locomotion', [r'locomotion', r'quadruped', r'biped(al)?', r'legged robot', r'gait', r'\bspot\b']),
    ('Navigation', [r'navigation', r'pointnav', r'objectnav', r'visual navigation', r'\bslam\b',
                    r'exploration', r'path planning']),
    ('World Model', [r'world model', r'video world model', r'latent dynamics', r'world action model']),
    # Note: 'WAM' in robotics also refers to Barrett Whole-Arm Manipulator, so we also add
    # a Hardware rule for Barrett WAM to keep that tag when only the arm is mentioned.

    ('Sim2Real', [r'sim2real', r'sim-to-real', r'domain random', r'domain adaptation']),
    ('Dexterous', [r'dexter(ous|ity)', r'in-hand manipulation', r'shadow hand', r'allegro hand',
                   r'barrett hand']),
    ('Imitation Learning', [r'imitation learning', r'behavior cloning', r'learning from demonstrations?',
                            r'diffusion policy', r'action chunk', r'act\b.*(policy|model|transformer)']),
    ('Reinforcement Learning', [r'reinforcement learning', r'policy gradient', r'\bppo\b', r'\bsac\b',
                                r'\brl\b.*policy']),
    ('LLM Agent', [r'large language model', r'\bllm\b', r'code as policies', r'saycan',
                   r'inner monologue', r'progprompt']),
    ('Teleoperation', [r'teleoperation', r'tele[- ]op(eration)?', r'remote operation', r'vr control']),
    ('Mobile Manipulation', [r'mobile manipulation', r'mobile manipulator', r'wheel.*arm']),
    ('Bimanual', [r'bimanual', r'dual[- ]arm', r'two[- ]hand', r'\baloha\b']),
    ('Dataset', [r'dataset', r'benchmark', r'open[- ]x', r'bridge data', r'open [x-]embodiment',
                 r'\bdroid\b']),
    ('Open-Source', [r'open[- ]source', r'open[- ]weights']),
    ('Simulator', [r'simulator', r'habitat', r'isaac(\s?sim|\s?lab|gym|\sgym)', r'mani[sk]ill',
                   r'robosuite', r'mujoco', r'pybullet', r'sapien']),
    ('Foundation Models', [r'foundation model', r'generalist policy', r'robot foundation model',
                           r'general-purpose robot', r'physical intelligence']),
    ('3D / Perception', [r'point cloud', r'3d (perception|representation|tracking|reconstruction)',
                         r'\bnerf\b', r'gaussian splat', r'object-centric', r'pose estimation']),
    ('Multi-task', [r'multi[- ]task', r'multitask', r'task generalization']),
    ('Tactile', [r'tactile', r'visuo[- ]tactile', r'visuotactile',
                 r'tactile (dataset|benchmark|sensor|perception|feedback|policy|manipulation)',
                 r'touch sensor', r'gel(sight|slim)']),
    ('Embodied Vision', [r'embodied (vision|ai|agent)', r'embodied question answering', r'\beqa\b']),
    ('Hardware', [r'\bfranka\b', r'\bpanda\b', r'\bkuka\b', r'\bur[ -]?\d', r'\bsawyer\b', r'\bbaxter\b',
                  r'\bfetch\b', r'\bunitree\b', r'\ballegro\b', r'shadow hand', r'barrett hand',
                  r'barrett\s+wam\b', r'\bwam\b\s*(arm|manipulator)', r'\baloha\b']),
    ('Autonomous Driving', [r'autonomous driving', r'self[- ]driving', r'driving policy',
                            r'urban driving', r'vehicle control']),
]

def classify_topics(text):
    t = text.lower()
    topics = []
    for name, pats in TOPIC_RULES:
        for pat in pats:
            if re.search(pat, t, flags=re.IGNORECASE):
                topics.append(name); break
    if re.search(r'\bcs\.ro\b', t) and 'Robotics' not in topics:
        topics.append('Robotics')
    if not topics and re.search(r'robot|robotic|embodied', t):
        topics.append('Robotics')
    # World Action Models (WAMs). The bare token 'WAM' is ambiguous (Barrett arm / Wannier / etc.),
    # so only treat it as WAM when either the full phrase appears, or 'WAM' appears WITHOUT
    # Barrett/arm/manipulator context in a paper that already has robotics keywords.
    wam_phrase = re.search(r'world[ -]?action[ -]?model', t, re.I)
    wam_acronym = bool(re.search(r'\bWAM\b', t)) and not re.search(
        r'barrett|whole[- ]arm|\bWAM\b\s*(arm|manipulator|cable|kinematic|hand)', t, re.I)
    if wam_phrase or wam_acronym:
        topics.append('WAM')
        if 'World Model' not in topics:
            topics.append('World Model')

    # de-dupe preserve order
    seen=set(); out=[]
    for x in topics:
        if x not in seen:
            seen.add(x); out.append(x)
    # If it's autonomous driving with no other embodied content, mark it as out-of-scope separately
    return out

def is_relevant(text, topics):
    t = text.lower()
    # Must explicitly talk about robots/embodied physical systems or a well-known robot platform.
    must_have = re.compile(
        r"\brobot(ics|ic)?\b|\bhumanoid\b|\bembodied\b|\bquadruped\b|\bbiped(al)?\b|\blegged( robot)?\b|"
        r"\blocomotion\b|\bdexter(ous|ity)\b|\bteleop(eration|er)?\b|\bbimanual\b|\bmanipulator\b|"
        r"\brobotic arm\b|\bgrasp(ing|er)?\b|\bmobile manipulation\b|\bsurgical robot\b|\bsim2real\b|"
        r"\bunitree\b|\bboston dynamics\b|\ballegro hand\b|\bshadow hand\b|\bbarrett hand\b|\bfranka\b|"
        r"\bpanda\b(?! )|\bkuka\b|\bur\s?\d\b|\bsawyer\b|\bbaxter\b|\bfetch robot\b|\baloha\b|\bmujoco\b|"
        r"\bisaac( sim| lab|gym)?\b|\bhabitat\b|\brobosuite\b|\bmaniskill\b|\bwam\b|\bwhole[- ]arm\b|"
        r"\brobotic manipulation\b|\bvision[- ]language[- ]action\b|\bvla\b|\btactile\b|"
        r"\bvisuo[- ]tactile\b|\bvisuotactile\b|\bdeformable[- ]object\b|\bsoft[- ]object\b|"
        r"\bcloth manipulation\b|\bphysical intelligence\b|\brobot foundation model\b|\bgeneralist robot\b|"
        r"\bcs\.ro\b"
    )
    if not must_have.search(t):
        return False
    # Exclude "robotic process automation/assessment" style business-process papers.
    if re.search(r"\brobotic process\b|\brobot process (automation|assessment|mining)\b|\brpa\b", t):
        if not re.search(r"\bmanipulat|\bgrasp|\bhumanoid|\bembodied|\bmobile robot|\brobotic arm|\blegged|\blocomotion|\bnavigat|\bteleop|\bdexter|\bbimanual", t):
            return False
    # Reject obvious non-robotics domains that reuse words like 'policy' / 'agent'.
    bad_domains = re.compile(
        r"financial|stock market|trading|blockchain|cryptocurrency|electronic health record|electronic medical record|"
        r"drug discovery|protein folding|molecular dynamics|natural language processing|recommender system|social network|"
        r"clinical trial|rag poisoning|database transaction|acid-compliant|audit-repair|process assessment|process benchmark"
    )
    if bad_domains.search(t):
        if not re.search(r"\brobot(ic|s)?\b|\bmanipulat|\bgrasp|\bhumanoid|\bembodied|\bsurgical robot|\btactile|\bdeformable[- ]object|\bsoft[- ]object|\bphysical intelligence", t):
            return False
    return True

def http_get(url, timeout=30):
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    with urllib.request.urlopen(req, context=CTX, timeout=timeout) as r:
        return r.read()

def http_post_json(url, payload, timeout=45):
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode('utf-8'),
        method='POST',
        headers={'User-Agent': UA, 'Content-Type': 'application/json'},
    )
    with urllib.request.urlopen(req, context=CTX, timeout=timeout) as r:
        return r.read()

# ---------- Hugging Face ----------
def fetch_hf_days(days=14):
    out = []
    today = datetime.now(timezone.utc).date()
    for i in range(days):
        d = today - timedelta(days=i)
        ds = d.isoformat()
        url = f'https://huggingface.co/api/daily_papers?date={ds}'
        try:
            raw = http_get(url)
            data = json.loads(raw)
        except Exception as e:
            print(f'[hf] skip {ds}: {e}', file=sys.stderr); continue
        if not isinstance(data, list): continue
        for item in data:
            meta = item.get('paper') or item
            pid = meta.get('id') or item.get('id')
            title = (meta.get('title') or '').strip().replace('\n',' ')
            summary = (meta.get('summary') or meta.get('abstract') or '').strip().replace('\n',' ')
            authors = ', '.join([(a.get('name') if isinstance(a,dict) else str(a))
                                 for a in (meta.get('authors') or []) if a])
            upvotes = meta.get('upvotes') or item.get('upvotes') or 0
            pdf = meta.get('pdf')
            aid = re.search(r'(\d{4}\.\d{4,5})', str(pid));
            if not aid: continue
            arxid = aid.group(1)
            text = f'{title} {summary} {authors}'
            topics = classify_topics(text)
            if not is_relevant(text, topics):
                continue
            out.append({
                'id': arxid,
                'title': ' '.join(title.split()),
                'abstract': ' '.join(summary.split()),
                'authors': ' '.join(authors.split()),
                'date': ds,
                'published': ds,
                'url': f'https://huggingface.co/papers/{arxid}',
                'hfUrl': f'https://huggingface.co/papers/{arxid}',
                'arxiv': f'https://arxiv.org/abs/{arxid}',
                'pdf': pdf or f'https://arxiv.org/pdf/{arxid}.pdf',
                'upvotes': int(upvotes or 0),
                'tags': topics[:5],
                'topics': topics,
                'source': 'hf',
            })
        time.sleep(0.2)
    return out

# ---------- arXiv ----------
ARXIV_NS = {'a':'http://www.w3.org/2005/Atom','arxiv':'http://arxiv.org/schemas/atom'}

def parse_arxiv(xml_bytes):
    root = ET.fromstring(xml_bytes)
    entries = []
    for e in root.findall('a:entry', ARXIV_NS):
        raw_id = (e.findtext('a:id', default='', namespaces=ARXIV_NS) or '').strip()
        title = (e.findtext('a:title', default='', namespaces=ARXIV_NS) or '').strip()
        summary = (e.findtext('a:summary', default='', namespaces=ARXIV_NS) or '').strip()
        published = (e.findtext('a:published', default='', namespaces=ARXIV_NS) or '')[:10]
        updated = (e.findtext('a:updated', default='', namespaces=ARXIV_NS) or '')[:10]
        authors = []
        for a in e.findall('a:author', ARXIV_NS):
            nm = a.findtext('a:name', default='', namespaces=ARXIV_NS)
            if nm: authors.append(nm.strip())
        cats = [c.attrib.get('term','') for c in e.findall('a:category', ARXIV_NS)]
        m = re.search(r'(\d{4}\.\d{4,5})', raw_id)
        if not m or not title or not summary: continue
        arxid = m.group(1)
        entries.append({
            'id': arxid,
            'title': ' '.join(title.split()),
            'abstract': ' '.join(summary.split()),
            'authors': ', '.join(authors),
            'date': published or updated,
            'published': published,
            'url': f'https://arxiv.org/abs/{arxid}',
            'arxiv': f'https://arxiv.org/abs/{arxid}',
            'pdf': f'https://arxiv.org/pdf/{arxid}.pdf',
            'upvotes': 0,
            'categories': cats,
            'source': 'arxiv',
        })
    return entries

def fetch_arxiv_max(query, start=0, max_results=200, attempts=3):
    params = {
        'search_query': query,
        'sortBy': 'submittedDate',
        'sortOrder': 'descending',
        'start': start,
        'max_results': max_results,
    }
    url = 'https://export.arxiv.org/api/query?' + urllib.parse.urlencode(params)
    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            raw = http_get(url, timeout=45)
            return parse_arxiv(raw)
        except Exception as e:
            last_error = e
            if attempt < attempts:
                time.sleep(3.5 * attempt)
    raise last_error

def arxiv_or(terms):
    return ' OR '.join(terms)

def fetch_arxiv(lookback_days=7, per_query=200):
    """
    Fire multiple arXiv queries to maximize recall.
    We cast a wide net across categories and combine with OR keywords.
    """
    cats = ['cs.RO','cs.AI','cs.CV','cs.LG','cs.MA','eess.SY','stat.ML','cs.HC']
    cat_or = arxiv_or([f'cat:{c}' for c in cats])
    robot_kw = arxiv_or(['all:embodied','all:robot','all:robotic','all:robotics','all:humanoid','all:locomotion','all:legged','all:navigation','all:teleoperation'])
    manipulation_kw = arxiv_or(['all:manipulation','all:manipulator','all:grasping','all:grasp','all:dexterous','all:bimanual','all:"mobile manipulation"','all:"motion planning"'])
    policy_kw = arxiv_or(['all:"vision-language-action"','all:VLA','all:"diffusion policy"','all:"behavior cloning"','all:"imitation learning"','all:"world model"','all:"world action model"','all:"end-to-end control"'])
    platform_kw = arxiv_or(['all:unitree','all:"pi 0"','all:π0','all:openvla','all:"open vla"','all:octo','all:aloha','all:franka','all:allegro','all:mujoco','all:isaac'])
    tactile_kw = arxiv_or(['all:tactile','all:"visuo tactile"','all:visuotactile','all:"deformable object"','all:"soft object"','all:"cloth manipulation"','all:"physical intelligence"','all:"robot foundation model"','all:"generalist robot"'])
    wam_or = arxiv_or(['ti:WAM', 'abs:"world action model"', 'abs:"world-action model"', 'ti:"world action model"'])
    wam_context_or = arxiv_or(['all:robot', 'all:robotic', 'all:embodied', 'all:manipulation', 'all:humanoid', 'all:navigation'])
    queries = [
        # Keep all recent Robotics-category submissions first. The downstream relevance filter
        # still removes obvious non-embodied false positives.
        ('cat:cs.RO', per_query),
        (f'({cat_or}) AND ({robot_kw})', 160),
        (f'({cat_or}) AND ({manipulation_kw})', 160),
        (f'({cat_or}) AND ({policy_kw})', 160),
        (f'({cat_or}) AND ({platform_kw})', 120),
        (f'({cat_or}) AND ({tactile_kw})', 120),
        # fall-back: explicit robot phrase even without category matches
        (f'ti:"robot"', 160),
        (f'ti:"humanoid"', 120),
        (f'ti:"VLA"', 80),
        (arxiv_or(['ti:"grasping"', 'ti:"manipulation"']), 160),
        (arxiv_or(['ti:"tactile"', 'ti:"visuo-tactile"', 'ti:"deformable"', 'ti:"soft object"']), 120),
        (f'({wam_or}) AND ({wam_context_or})', 80),
    ]
    out, seen = [], set()
    cutoff = (datetime.now(timezone.utc).date() - timedelta(days=lookback_days)).isoformat()
    for q, max_results in queries:
        try:
            entries = fetch_arxiv_max(q, start=0, max_results=max_results)
        except Exception as e:
            print(f'[arxiv] query failed ({q[:60]}...): {e}', file=sys.stderr)
            time.sleep(3.1); continue
        kept = 0
        for ent in entries:
            if ent['id'] in seen: continue
            # Only keep papers within the lookback window
            if (ent.get('date') or '0000-00-00') < cutoff: continue
            text = f"{ent['title']} {ent['abstract']} {' '.join(ent.get('categories',[]))}"
            topics = classify_topics(text)
            if not is_relevant(text, topics): continue
            ent['topics'] = topics
            ent['tags'] = topics[:5]
            out.append(ent); seen.add(ent['id']); kept += 1
        print(f'[arxiv] query kept {kept} new entries', file=sys.stderr)
        time.sleep(3.1)  # respect arXiv rate limit
    return out

# ---------- History ----------
def load_history():
    if HISTORY_PATH.exists():
        try:
            data = json.loads(HISTORY_PATH.read_text(encoding='utf-8'))
            if isinstance(data, dict) and 'papers' in data:
                return data
        except Exception:
            pass
    return {'papers': {}, 'generatedAt': None}

def save_history(hist):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    HISTORY_PATH.write_text(json.dumps(hist, ensure_ascii=False, indent=2), encoding='utf-8')

def merge_into_history(hist, new_papers):
    """Merge fetched papers into persistent history by id, never deleting old entries."""
    now = datetime.now(timezone.utc).isoformat()
    papers = hist.setdefault('papers', {})
    added = 0
    for p in new_papers:
        cur = papers.get(p['id'])
        if cur is None:
            papers[p['id']] = p
            added += 1
        else:
            # Update mutable fields (HF upvotes may grow over time)
            cur['upvotes'] = max(int(cur.get('upvotes',0)), int(p.get('upvotes',0)))
            cur['topics'] = list(dict.fromkeys((p.get('topics') or []) + (cur.get('topics') or [])))[:8]
            cur['tags'] = cur['topics'][:5]
            if p.get('source') == 'hf': cur['source'] = 'hf'  # hf as "verified" source
            if p.get('hfUrl'): cur['hfUrl'] = p['hfUrl']
            # Keep earliest date seen
            if not cur.get('date') or (p.get('date') and p['date'] < cur['date']):
                cur['date'] = p['date']
    hist['generatedAt'] = now
    return added

def best_venue_from_semantic_scholar(meta):
    if not meta:
        return None
    venue = meta.get('publicationVenue') or {}
    journal = meta.get('journal') or {}
    names = []
    if venue.get('name'):
        names.append(venue['name'])
    names.extend(venue.get('alternate_names') or [])
    if meta.get('venue'):
        names.append(meta['venue'])
    if journal.get('name') and journal.get('name').lower() != 'arxiv':
        names.append(journal['name'])
    clean = []
    for name in names:
        name = ' '.join(str(name).split())
        if name and name.lower() not in {'arxiv', 'arxiv.org'} and name not in clean:
            clean.append(name)
    if not clean:
        return None
    short = [name for name in clean if len(name) <= 14 and any(c.isupper() for c in name)]
    label = short[0] if short else clean[0]
    year = meta.get('year')
    if year and str(year) not in label:
        label = f'{label} {year}'
    return {
        'venue': label,
        'venueName': clean[0],
        'venueType': venue.get('type') or ('journal' if journal else None),
        'venueUrl': venue.get('url'),
        'publicationYear': year,
    }

def enrich_venues(hist, max_papers=40):
    """Cache conference/journal metadata incrementally; falls back cleanly when unavailable."""
    if max_papers <= 0:
        return 0
    papers = sorted(hist.get('papers', {}).values(), key=lambda p: p.get('date') or '', reverse=True)
    candidates = []
    retry_before = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    for p in papers:
        if p.get('venue'):
            continue
        if p.get('venueLookup') == 'not_found' and p.get('venueCheckedAt', '') >= retry_before:
            continue
        m = re.search(r'(\d{4}\.\d{4,5})', (p.get('id') or '') + ' ' + (p.get('arxiv') or ''))
        if not m:
            continue
        candidates.append((m.group(1), p))
        if len(candidates) >= max_papers:
            break
    if not candidates:
        return 0
    fields = 'title,venue,publicationVenue,journal,year,externalIds'
    url = 'https://api.semanticscholar.org/graph/v1/paper/batch?' + urllib.parse.urlencode({'fields': fields})
    updated = 0
    for start in range(0, len(candidates), 100):
        batch = candidates[start:start+100]
        try:
            raw = http_post_json(url, {'ids': [f'ARXIV:{aid}' for aid, _ in batch]}, timeout=45)
            results = json.loads(raw)
        except Exception as e:
            print(f'[venue] Semantic Scholar batch failed: {e}', file=sys.stderr)
            time.sleep(2)
            continue
        for (_, paper), meta in zip(batch, results):
            info = best_venue_from_semantic_scholar(meta)
            if info:
                paper.update({k: v for k, v in info.items() if v})
                paper['venueLookup'] = 'found'
                updated += 1
            else:
                paper['venueLookup'] = 'not_found'
            paper['venueCheckedAt'] = datetime.now(timezone.utc).isoformat()
        time.sleep(1.2)
    return updated

def venue_name(p):
    return ' '.join(str(p.get('venueName') or p.get('venue') or '').split())

def has_real_venue(p):
    name = venue_name(p)
    return bool(name) and not re.search(r'^(arxiv|arxiv\.org|hf daily|hugging face daily|preprint|预印本)$', name, re.I) and not re.search(r'^cs\.', name, re.I)

def publication_kind(p):
    if not has_real_venue(p):
        return '预印本'
    typ = str(p.get('venueType') or '').lower()
    name = venue_name(p)
    if 'journal' in typ:
        return '期刊'
    if 'conference' in typ:
        return '会议'
    if re.search(r'\b(journal|letters|transactions|t-?ro|ra-?l)\b|science robotics|autonomous robots|robotics and automation letters', name, re.I):
        return '期刊'
    if re.search(r'\b(icra|iros|corl|rss|cvpr|iccv|eccv|neurips|nips|icml|iclr|aaai|ijcai|acl|emnlp|naacl|chi|hri|uist|siggraph|case)\b', name, re.I):
        return '会议'
    return '已收录'

def publication_counts(papers):
    counts = {}
    for p in papers:
        kind = publication_kind(p)
        counts[kind] = counts.get(kind, 0) + 1
    return counts

def topic_counts(papers):
    counts = {}
    for p in papers:
        for topic in p.get('topics') or p.get('tags') or []:
            counts[topic] = counts.get(topic, 0) + 1
    return counts

# ---------- Build ----------
def build_bundle(hist, recent_days=7, archive_days=5*365, limit=None, archive_limit=None, venue_limit=40):
    hf = fetch_hf_days(days=14)
    arx = fetch_arxiv(lookback_days=7, per_query=300)
    # Merge sources by id (hf wins over arxiv when same id)
    by_id = {p['id']: dict(p) for p in arx}
    for p in hf:
        cur = by_id.get(p['id'])
        if cur:
            cur['source'] = 'hf'
            cur['upvotes'] = max(int(cur.get('upvotes',0)), int(p.get('upvotes',0)))
            cur['hfUrl'] = p.get('hfUrl')
            cur['url'] = p['url']
            cur['topics'] = list(dict.fromkeys((p.get('topics') or []) + (cur.get('topics') or [])))[:8]
            cur['tags'] = cur['topics'][:5]
            if p.get('date'): cur['date'] = p['date']
        else:
            by_id[p['id']] = dict(p)
    papers = list(by_id.values())
    # Merge into history
    added = merge_into_history(hist, papers)
    venue_updates = enrich_venues(hist, max_papers=venue_limit)
    # Build two views:
    #   - recent: last `recent_days` days (shown on the homepage's "最新" panel)
    #   - archive: everything older than `recent_days` but within `archive_days`
    all_hist = list(hist['papers'].values())
    today = datetime.now(timezone.utc).date()
    recent_cutoff = (today - timedelta(days=recent_days)).isoformat()
    archive_cutoff = (today - timedelta(days=archive_days)).isoformat()
    def keyf(p):
        return ((p.get('date') or '0000-00-00'),
                1 if p.get('source')=='hf' else 0,
                int(p.get('upvotes') or 0),
                len(p.get('topics') or []))
    recent = sorted([p for p in all_hist if (p.get('date') or '0000-00-00') >= recent_cutoff], key=keyf, reverse=True)
    archive = sorted([p for p in all_hist
                       if archive_cutoff <= (p.get('date') or '0000-00-00') < recent_cutoff],
                      key=keyf, reverse=True)
    recent_total = len(recent)
    archive_total = len(archive)
    if limit is not None:
        recent = recent[:limit]
    if archive_limit is not None:
        archive = archive[:archive_limit]
    bundle = {
        'generatedAt': hist.get('generatedAt'),
        'recentDays': recent_days,
        'archiveDays': archive_days,
        'recentCutoff': recent_cutoff,
        'archiveCutoff': archive_cutoff,
        'addedToday': added,
        'venueUpdates': venue_updates,
        'historyTotal': len(hist.get('papers',{})),
        'publicationCounts': publication_counts(all_hist),
        'topicCounts': topic_counts(all_hist),
        'recentTotal': recent_total,
        'count': len(recent),
        'archiveCount': len(archive),
        'archiveTotal': archive_total,
        'sources': {
            'hf': sum(1 for p in recent if p.get('source')=='hf'),
            'arxiv': sum(1 for p in recent if p.get('source')=='arxiv'),
        },
        'archiveSources': {
            'hf': sum(1 for p in archive if p.get('source')=='hf'),
            'arxiv': sum(1 for p in archive if p.get('source')=='arxiv'),
        },
        'warnings': [],
        'papers': recent,
        'archive': archive,
    }
    if bundle['count'] == 0:
        bundle['warnings'].append('zero_papers')
    return bundle

def write_archive_shards(hist, bundle):
    """Write complete archive as lightweight per-year files for lazy frontend loading."""
    archive_dir = DATA_DIR / 'archive'
    archive_dir.mkdir(parents=True, exist_ok=True)
    for old in archive_dir.glob('*.json'):
        old.unlink()
    recent_cutoff = bundle.get('recentCutoff') or '9999-99-99'
    archive_cutoff = bundle.get('archiveCutoff') or '0000-00-00'
    papers = [
        p for p in hist.get('papers', {}).values()
        if archive_cutoff <= (p.get('date') or '0000-00-00') < recent_cutoff
    ]
    def keyf(p):
        return ((p.get('date') or '0000-00-00'),
                1 if p.get('source')=='hf' else 0,
                int(p.get('upvotes') or 0),
                len(p.get('topics') or []))
    papers = sorted(papers, key=keyf, reverse=True)
    by_year = {}
    for p in papers:
        year = (p.get('date') or '0000')[:4]
        if not year.isdigit():
            continue
        by_year.setdefault(year, []).append(p)
    index = {
        'generatedAt': hist.get('generatedAt'),
        'archiveTotal': len(papers),
        'publicationCounts': publication_counts(papers),
        'topicCounts': topic_counts(papers),
        'recentCutoff': recent_cutoff,
        'archiveCutoff': archive_cutoff,
        'years': [],
    }
    for year in sorted(by_year.keys(), reverse=True):
        items = by_year[year]
        months = {}
        for p in items:
            ym = (p.get('date') or '')[:7]
            if ym:
                months[ym] = months.get(ym, 0) + 1
        (archive_dir / f'{year}.json').write_text(
            json.dumps({'year': year, 'count': len(items), 'papers': items}, ensure_ascii=False, indent=2),
            encoding='utf-8'
        )
        index['years'].append({
            'year': year,
            'count': len(items),
            'months': [{'month': m, 'count': months[m]} for m in sorted(months.keys(), reverse=True)],
            'path': f'data/archive/{year}.json',
        })
    (DATA_DIR / 'archive-index.json').write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'[build] wrote archive shards: years={len(index["years"])}, total={index["archiveTotal"]}')

def compact_search_paper(p):
    keep = {
        'id', 'title', 'authors', 'date', 'published', 'source', 'topics', 'tags',
        'arxiv', 'pdf', 'url', 'hfUrl', 'upvotes', 'venue', 'venueName', 'venueType',
        'publicationYear',
    }
    out = {k: p.get(k) for k in keep if p.get(k) not in (None, '', [])}
    abstract = ' '.join((p.get('abstract') or '').split())
    if abstract:
        out['abstract'] = abstract[:360]
    return out

def compact_display_paper(p, abstract_limit=520):
    keep = {
        'id', 'title', 'authors', 'date', 'published', 'source', 'topics', 'tags',
        'categories', 'arxiv', 'pdf', 'url', 'hfUrl', 'upvotes', 'venue', 'venueName',
        'venueType', 'publicationYear',
    }
    out = {k: p.get(k) for k in keep if p.get(k) not in (None, '', [])}
    abstract = ' '.join((p.get('abstract') or '').split())
    if abstract:
        out['abstract'] = abstract[:abstract_limit]
    return out

def make_bundle_view(bundle, paper_limit=None, compact=True):
    view = dict(bundle)
    papers = list(bundle.get('papers') or [])
    if paper_limit is not None:
        papers = papers[:paper_limit]
    if compact:
        papers = [compact_display_paper(p) for p in papers]
    view['papers'] = papers
    view['archive'] = []
    view['count'] = len(papers)
    view['latestPath'] = 'data/latest.json'
    view['archiveIndexPath'] = 'data/archive-index.json'
    view['searchIndexPath'] = 'data/search-index.json'
    return view

def write_json(path, data, *, indent=None):
    if indent is None:
        text = json.dumps(data, ensure_ascii=False, separators=(',', ':'))
    else:
        text = json.dumps(data, ensure_ascii=False, indent=indent)
    path.write_text(text, encoding='utf-8')

def write_search_index(hist):
    """Write a compact all-history index for lazy full-site search."""
    papers = sorted(
        hist.get('papers', {}).values(),
        key=lambda p: ((p.get('date') or '0000-00-00'), int(p.get('upvotes') or 0)),
        reverse=True,
    )
    index = {
        'generatedAt': hist.get('generatedAt'),
        'count': len(papers),
        'papers': [compact_search_paper(p) for p in papers],
    }
    SEARCH_INDEX_PATH.write_text(json.dumps(index, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    print(f'[build] wrote {SEARCH_INDEX_PATH}: count={len(papers)}')

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--stdout', action='store_true')
    ap.add_argument('--recent', type=int, default=7, help='how many days to show in "latest" (default 7)')
    ap.add_argument('--archive', type=int, default=5*365, help='how many days back the "archive" tab covers (default 365)')
    ap.add_argument('--limit', type=int, default=None, help='max papers shown in "latest" (default: all)')
    ap.add_argument('--archive-limit', dest='archive_limit', type=int, default=None, help='max papers shown in "archive" (default: all)')
    ap.add_argument('--venue-limit', type=int, default=40, help='max papers to enrich with conference/journal metadata per run')
    args = ap.parse_args()

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    hist = load_history()
    bundle = build_bundle(hist, recent_days=args.recent, archive_days=args.archive, limit=args.limit, archive_limit=args.archive_limit, venue_limit=args.venue_limit)
    save_history(hist)
    latest_bundle = make_bundle_view(bundle, paper_limit=None, compact=True)
    light_bundle = make_bundle_view(bundle, paper_limit=36, compact=True)
    write_json(LATEST_PATH, latest_bundle)
    write_json(OUT_PATH, light_bundle)
    BOOTSTRAP_PATH.write_text(
        'window.__BUNDLE__=' + json.dumps(light_bundle, ensure_ascii=False, separators=(',', ':')).replace('<', '\\u003c') + ';\n',
        encoding='utf-8',
    )
    write_archive_shards(hist, bundle)
    write_search_index(hist)
    print(f'[build] wrote {OUT_PATH}: bootstrap={light_bundle["count"]}/{bundle["count"]}, latest={bundle["count"]} (HF={bundle["sources"]["hf"]}, arXiv={bundle["sources"]["arxiv"]}), '
          f'archive={bundle["archiveCount"]} (HF={bundle["archiveSources"]["hf"]}, arXiv={bundle["archiveSources"]["arxiv"]}), '
          f'addedToday={bundle["addedToday"]}, venueUpdates={bundle["venueUpdates"]}, historyTotal={bundle["historyTotal"]})')
    if bundle['warnings']:
        print('[build] warnings:', ','.join(bundle['warnings']))
    if args.stdout:
        json.dump(bundle, sys.stdout, ensure_ascii=False, indent=2); sys.stdout.write('\n')

if __name__ == '__main__':
    main()
