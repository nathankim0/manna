# 오늘의 만나 백업

JBCH 공식 소스의 날짜를 확인한 본문만 저장합니다. 이 저장소의 GitHub Actions가 앱 서버·로컬 Mac과 독립적으로 수집합니다.

- `.github/workflows/refresh-manna.yml`: UTC `3,33 0,3,6,9,12,14,18,21 * * *`, 수동 실행 가능. 스케줄은 GitHub 상황에 따라 지연될 수 있습니다.
- `JBCH_USER_ID`, `JBCH_PASSWORD`: 기존 계정의 Actions Secrets. 값·쿠키는 로그나 파일에 기록하지 않습니다. 계정 변경 시 BibleHabit 서버와 함께 갱신합니다.
- `process_result.json`: 기존 `bookname`·`sentence` 배열 호환 유지.
- `manna_metadata.json`: 실제 소스 날짜·참조·구절 수·수집 시각·본문 SHA-256. 소비자는 동일 커밋의 두 파일을 읽고 날짜·해시를 검증해야 합니다. 커밋 시각을 소스 날짜로 대신하지 않습니다.
- 요청당 10초, 일시 연결 오류·502/503/504만 최대 3회. 날짜 불일치·빈 본문·파싱 실패 때 기존 백업을 유지하며 실행은 실패 처리합니다. 인증·권한·429는 재시도하지 않습니다.
- 같은 날짜·본문은 불필요하게 재커밋하지 않습니다. 같은 본문이 다음 날짜에 다시 나와도 날짜 메타데이터는 갱신됩니다.

검증: `python3 -m unittest discover -s tests -v`.
실제 수집: 두 환경변수를 안전하게 주입한 환경에서 `python3 scripts/collect_manna.py`.

본문은 JBCH 공식 응답 그대로이며 출처는 [생명의말씀선교회 오늘의 만나](https://bible.jbch.org/manna.php)입니다. 자료의 권리·이용 조건은 원출처에 따릅니다.
