#!/usr/bin/env python3
"""Collect verified JBCH daily manna; no external packages or credential output."""
import datetime as dt
import hashlib
import http.cookiejar
import json
import os
from pathlib import Path
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from zoneinfo import ZoneInfo

LOGIN = 'https://community.jbch.org/login.php?go=yes&dev_name=bible&url=https%3A%2F%2Fbible.jbch.org%2Fmanna.php'
PAGE = 'https://bible.jbch.org/manna.php'
API = 'https://bible.jbch.org/inc/process.php'
MOBILE = 'https://m.jbch.org/common/inc/process.php'
TIMEOUT = 10
MAX_ATTEMPTS = 3


class Node:
    def __init__(self, tag='', attrs=()):
        self.tag, self.attrs, self.children = tag, dict(attrs), []

    def text(self):
        return ''.join(child.text() if isinstance(child, Node) else child for child in self.children)

    def all(self, tag=None, cls=None):
        found = []
        for child in self.children:
            if isinstance(child, Node):
                if (tag is None or child.tag == tag) and (cls is None or cls in child.attrs.get('class', '').split()):
                    found.append(child)
                found.extend(child.all(tag, cls))
        return found


class Document(HTMLParser):
    VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}

    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.root = Node()
        self.stack = [self.root]
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs)
        self.stack[-1].children.append(node)
        if tag not in self.VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self.VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        self.stack[-1].children.append(data)


class JbchClient:
    def __init__(self):
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))

    def request(self, url, data=None):
        headers = {
            'User-Agent': 'Mozilla/5.0 BibleHabit-MannaBackup/1.0',
            'Accept-Language': 'ko-KR,ko;q=0.9',
            'Referer': PAGE,
        }
        body = None
        if data is not None:
            body = urllib.parse.urlencode(data).encode()
            headers['Content-Type'] = 'application/x-www-form-urlencoded; charset=UTF-8'
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                with self.opener.open(urllib.request.Request(url, data=body, headers=headers), timeout=TIMEOUT) as response:
                    content = response.read(2_000_001)
                    if len(content) > 2_000_000:
                        raise ValueError('Source response exceeds size limit')
                    return content.decode('utf-8')
            except urllib.error.HTTPError as error:
                status = error.code
                error.close()
                if status not in (502, 503, 504) or attempt == MAX_ATTEMPTS:
                    raise RuntimeError(f'JBCH HTTP {status}; attempts={attempt}') from None
            except (urllib.error.URLError, TimeoutError, socket.timeout, ConnectionError):
                if attempt == MAX_ATTEMPTS:
                    # Do not expose urllib's error string: it can contain URLs.
                    raise RuntimeError(f'JBCH connection failure; attempts={attempt}') from None
            time.sleep(0.5 * attempt)

    def login(self, user, password):
        root = Document(self.request(LOGIN)).root
        forms = root.all('form')
        action = forms[0].attrs.get('action', '/member/login_ok.php') if forms else '/member/login_ok.php'
        target = urllib.parse.urljoin('https://community.jbch.org', action)
        parsed = urllib.parse.urlparse(target)
        if parsed.scheme != 'https' or parsed.hostname != 'community.jbch.org':
            raise ValueError('Unexpected JBCH login destination')
        self.request(target, {
            'user_id': user, 'passwd': password, 'mode': 'loginCheck',
            'go': 'yes', 'dev_name': 'bible', 'url': PAGE, 'LoginButton': 'LoginButton',
        })
        cookie_names = {cookie.name for cookie in self.jar}
        if not {'hash', 'intMemberUid'} <= cookie_names:
            raise RuntimeError('JBCH login cookies unavailable')


def select_subject(date_key, request):
    body = json.loads(request(API + '?mode=manna', {
        'dev_name': 'bible', 'tokenId': 'DKEIMFFOQIE8JFNV9QUQ3NFROQ0QKLIUF9Q9UEFHAUFQUE8F',
        'boardId': '5514', 'open_date': date_key, 'limit': '1', 'chId': '3', 'flag': '4', 'use_kind': '1',
    }))
    items = body if isinstance(body, list) else body.get('result', [])
    for item in items:
        if str(item.get('opened', ''))[:10] == date_key and str(item.get('subject', '')).strip():
            return item['subject'].strip()
    mobile = request(MOBILE, {
        'mode': 'loadBoardInf', 'cId': '534', 'pgname': 'mcontent', 'listType': 'card',
        'length': '10', 'start': '0', 'order_column': 'dw.date', 'order_dir': 'desc', 'viewType': 'board', 'col': '6',
    }).split('@@')
    if len(mobile) < 8 or mobile[1] != 'ok':
        raise ValueError('Invalid official mobile schedule')
    for link in Document(mobile[7]).root.all('a', 'viewLink'):
        dates = link.all('h7')
        if dates and dates[0].text().strip() == date_key and link.attrs.get('data-conname', '').strip():
            return link.attrs['data-conname'].strip()
    raise ValueError(f'No verified JBCH schedule for {date_key}')


def parse_verses(html):
    verses = []
    for node in Document(html).root.all(cls='sentenceBox'):
        sentences = node.all(cls='sentence')
        bookname = ' '.join(node.attrs.get('data-bookname', '').split())
        sentence = ''.join(item.text() for item in sentences).strip()
        if not sentence or not bookname or ' ' not in bookname:
            raise ValueError('Invalid JBCH verse')
        verses.append({'bookname': bookname, 'sentence': sentence})
    if not 1 <= len(verses) <= 200 or len({v['bookname'] for v in verses}) != len(verses):
        raise ValueError('Invalid JBCH verse count or duplicate reference')
    return verses


def collect(date_key, request):
    subject = select_subject(date_key, request)
    verses = parse_verses(request(API, {'mode': 'searchBible', 'keyword': subject}))
    return subject, verses


def write_backup(directory, date_key, subject, verses, now):
    payload = (json.dumps(verses, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    digest = hashlib.sha256(payload).hexdigest()
    path = directory / 'manna_metadata.json'
    if path.exists() and (directory / 'process_result.json').exists():
        previous = json.loads(path.read_text())
        if (previous.get('dateKey') == date_key and previous.get('sha256') == digest
                and previous.get('referenceText') == subject
                and (directory / 'process_result.json').read_bytes() == payload):
            return False
    metadata = {
        'schemaVersion': 1, 'dateKey': date_key, 'referenceText': subject,
        'verseCount': len(verses), 'source': 'jbch', 'fetchedAt': now.isoformat().replace('+00:00', 'Z'),
        'sha256': digest,
    }
    # No write happens before source-date validation and complete parsing succeed.
    (directory / 'process_result.json').write_bytes(payload)
    path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return True


def main():
    now = dt.datetime.now(dt.timezone.utc)
    date_key = now.astimezone(ZoneInfo('Asia/Seoul')).date().isoformat()
    user, password = os.environ.get('JBCH_USER_ID', ''), os.environ.get('JBCH_PASSWORD', '')
    if not user or not password:
        raise ValueError('JBCH credentials are required')
    client = JbchClient()
    client.login(user, password)
    subject, verses = collect(date_key, client.request)
    changed = write_backup(Path(__file__).resolve().parents[1], date_key, subject, verses, now)
    print(json.dumps({'dateKey': date_key, 'referenceText': subject, 'verseCount': len(verses), 'changed': changed}, ensure_ascii=False))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        # All known errors are fixed strings; never emit arbitrary exception text.
        print(f'Manna backup failed ({type(error).__name__}); previous backup preserved')
        raise SystemExit(1)
