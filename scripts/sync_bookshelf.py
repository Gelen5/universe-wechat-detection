"""Refresh the cached Star snapshot manually; never fetch or republish book text."""
import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

CATALOG = Path(__file__).resolve().parents[1] / 'static/bookshelf-data.json'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--force', action='store_true', help='Refresh even if the snapshot is less than 24 hours old')
    args = parser.parse_args()
    catalog = json.loads(CATALOG.read_text(encoding='utf-8'))
    now = datetime.now(timezone.utc)
    age = (now - datetime.fromisoformat(catalog['updatedAt'].replace('Z', '+00:00'))).total_seconds()
    if age < 86400 and not args.force:
        print('Snapshot is less than 24 hours old; using the cache.')
        return
    headers = {'User-Agent': 'Universe-AI-Bookshelf', 'Accept': 'application/vnd.github+json'}
    token = os.environ.get('GITHUB_TOKEN')
    if token:
        headers['Authorization'] = 'Bearer ' + token
    stamp = now.isoformat(timespec='seconds')
    try:
        for book in catalog['books']:
            owner_repo = book['githubUrl'].removeprefix('https://github.com/')
            if not owner_repo.startswith('alchaincyf/') or len(owner_repo.split('/')) != 2:
                raise ValueError('Unexpected repository; review the curated record first')
            request = Request('https://api.github.com/repos/' + owner_repo, headers=headers)
            with urlopen(request, timeout=20) as response:
                data = json.load(response)
            stars = data['stargazers_count']
            if type(stars) is not int or stars < 0:
                raise ValueError('Invalid Star count')
            book['stars'] = stars
            book['starsUpdatedAt'] = stamp
        catalog['updatedAt'] = stamp
        temporary = CATALOG.with_suffix('.json.tmp')
        temporary.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        temporary.replace(CATALOG)
    except Exception as exc:
        # Never print response bodies or authorization headers. Preserve the old snapshot.
        raise SystemExit(f'Sync failed ({type(exc).__name__}); existing snapshot retained.') from None
    print(f'Updated {len(catalog["books"])} Star counts. Review and deploy the JSON file normally.')


if __name__ == '__main__':
    main()
