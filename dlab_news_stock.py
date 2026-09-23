#!/usr/bin/env python3
"""Validate and merge verified dlab articles collected by the recurring task."""
import argparse
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parent
BANK_PATH = ROOT / 'data/dlab_news/news_stock.json'
JST = timezone(timedelta(hours=9))
MAX_AGE_DAYS = 14


def timestamp(value):
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('Timestamp must include a timezone')
    return parsed


def canonical_url(value):
    parsed = urlsplit(value)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('Expected an https article URL')
    if any(c in value for c in '<>|\r\n '):
        raise ValueError('Invalid characters in article URL')
    return urlunsplit(('https', parsed.netloc.lower(), parsed.path.rstrip('/'), '', ''))


def validate_article(article, now):
    result = dict(article)
    for field, maximum in (('title', 250), ('summary', 700), ('detail', 2500)):
        value = result.get(field)
        if not isinstance(value, str) or not value.strip() or len(value) > maximum:
            raise ValueError(f'Invalid {field}')
        result[field] = value.strip()
    result['dlab_url'] = canonical_url(result['dlab_url'])
    parsed = urlsplit(result['dlab_url'])
    if parsed.hostname != 'daigovideolab.jp' or not parsed.path.startswith('/blog/'):
        raise ValueError('Expected a dlab blog URL')
    # Source query parameters may identify the article, so retain them.
    canonical_url(result['url'])
    published = date.fromisoformat(result['published'])
    if published > now.astimezone(JST).date():
        raise ValueError('Future publication date')
    collected = timestamp(result['collected_at'])
    if collected > now + timedelta(minutes=5):
        raise ValueError('Future collection timestamp')
    return result


def load_bank(path=BANK_PATH, now=None):
    now = now or datetime.now(timezone.utc)
    bank = json.loads(Path(path).read_text(encoding='utf-8'))
    if bank.get('schema_version') != 1:
        raise ValueError('Unsupported news stock schema')
    if timestamp(bank['last_checked_at']) > now + timedelta(minutes=5):
        raise ValueError('Future check timestamp')
    bank['articles'] = [validate_article(a, now) for a in bank['articles']]
    ids = [a['dlab_url'] for a in bank['articles']]
    if len(ids) != len(set(ids)):
        raise ValueError('Duplicate dlab URL in stock')
    return bank


def save_json(path, data):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)


def merge_articles(bank, incoming, now):
    """Rechecking a URL never makes an old article new."""
    articles = {a['dlab_url']: dict(a) for a in bank['articles']}
    added = 0
    for raw in incoming:
        article = validate_article(raw, now)
        key = article['dlab_url']
        if key in articles:
            article['published'] = articles[key]['published']
            article['collected_at'] = articles[key]['collected_at']
        else:
            added += 1
        articles[key] = article
    return {
        'schema_version': 1,
        'last_checked_at': now.isoformat(),
        'articles': sorted(articles.values(), key=lambda a: (a['published'], a['dlab_url']), reverse=True),
    }, added


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--import-file', type=Path, help='JSON array of verified articles; [] records a successful check')
    args = parser.parse_args()
    now = datetime.now(timezone.utc)
    bank = load_bank(now=now)
    if args.import_file:
        incoming = json.loads(args.import_file.read_text(encoding='utf-8'))
        if not isinstance(incoming, list):
            raise ValueError('Import must be an array')
        bank, added = merge_articles(bank, incoming, now)
        save_json(BANK_PATH, bank)
        print(f"Added {added} articles; stock has {len(bank['articles'])} articles")
    else:
        print(f"Valid stock: {len(bank['articles'])} articles; last check: {bank['last_checked_at']}")


if __name__ == '__main__':
    main()
