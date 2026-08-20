"""Incrementally enrich cached papers with conference/journal metadata."""
import argparse
import json
from pathlib import Path

import build_daily as bd


def refresh_bundle_from_history(hist, bundle):
    papers = hist.get('papers', {})
    for key in ('papers', 'archive'):
        bundle[key] = [papers.get(p.get('id'), p) for p in bundle.get(key, [])]
    archive = bundle.get('archive') or []
    bundle['archiveCount'] = len(archive)
    bundle['archiveTotal'] = bundle.get('archiveTotal') or bundle.get('historyTotal') or len(archive)
    bundle['archiveSources'] = {
        'hf': sum(1 for p in archive if p.get('source') == 'hf'),
        'arxiv': sum(1 for p in archive if p.get('source') == 'arxiv'),
    }
    bundle['publicationCounts'] = bd.publication_counts(papers.values())
    bundle['notes'] = [
        'archive is split by year under data/archive/ for fast lazy loading; data/history.json keeps the complete database'
    ]
    return bundle


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--max-papers', type=int, default=40)
    args = ap.parse_args()

    hist = bd.load_history()
    updated = bd.enrich_venues(hist, max_papers=args.max_papers)
    bd.save_history(hist)

    if bd.OUT_PATH.exists():
        bundle = json.loads(bd.OUT_PATH.read_text(encoding='utf-8'))
    else:
        bundle = {
            'papers': [],
            'archive': [],
            'historyTotal': len(hist.get('papers', {})),
            'archiveTotal': len(hist.get('papers', {})),
        }
    bundle['venueUpdates'] = updated
    bundle = refresh_bundle_from_history(hist, bundle)
    bd.OUT_PATH.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding='utf-8')
    bd.write_archive_shards(hist, bundle)
    print(f'[venue] updated={updated}, historyTotal={len(hist.get("papers", {}))}')


if __name__ == '__main__':
    main()
