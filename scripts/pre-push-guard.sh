#!/bin/sh
# 실제 운임·브랜드명 같은 비공개 값이 들어 있는 커밋이 GitHub(공개 저장소)로 올라가는 것을 막는 pre-push 훅.
#
# 푸시하려는 각 커밋의 파일 내용에서, 패턴 파일에 적힌 문구를 찾는다. 하나라도 있으면 푸시를 중단한다.
# 차단할 문구는 이 스크립트가 아니라 로컬 패턴 파일에 둔다 (그래야 스크립트를 저장소에 올려도 안전하다):
#     <저장소>/.git/push-block-patterns     한 줄에 문구 하나 (고정 문자열, 정규식 아님)
# 패턴 파일이 없으면 검사하지 않고 경고만 낸다.
#
# 설치 (저장소 루트에서 한 번):
#     git show origin/main:scripts/pre-push-guard.sh > .git/hooks/pre-push && chmod +x .git/hooks/pre-push
#     printf '%s\n' '차단할 문구1' '차단할 문구2' > .git/push-block-patterns
# 정말 올려도 되는 경우에만 `git push --no-verify` 로 우회한다.
zero=0000000000000000000000000000000000000000
patterns="${PUSH_BLOCK_PATTERNS:-$(git rev-parse --git-common-dir)/push-block-patterns}"

if [ ! -s "$patterns" ]; then
  echo "[pre-push] 패턴 파일($patterns)이 없어 비공개 값 검사를 건너뜁니다." >&2
  exit 0
fi

bad=0
while read -r local_ref local_sha remote_ref remote_sha; do
  [ "$local_sha" = "$zero" ] && continue          # 브랜치 삭제는 통과
  # -F: 고정 문자열, -f: 패턴 파일. .claude 폴더(작업트리 메모)는 제외
  hit=$(git grep -l -F -f "$patterns" "$local_sha" -- . ':!.claude' 2>/dev/null | head -3)
  if [ -n "$hit" ]; then
    echo "[푸시 차단] $local_ref 에 비공개 값이 들어 있습니다:" >&2
    echo "$hit" | sed 's/^/    /' >&2
    bad=1
  fi
done

if [ "$bad" = 1 ]; then
  echo "실제 값은 config/factory.local.yaml 과 .env(BRAND_NAME)에만 두세요. 이 브랜치는 올리지 마세요." >&2
  exit 1
fi
exit 0
