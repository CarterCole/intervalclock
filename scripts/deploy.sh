#!/usr/bin/env bash
# Publish web/ to clock.cartercole.net: a private S3 bucket behind CloudFront.
#
# Runs from CI (which assumes an OIDC role) and from a laptop with AWS
# credentials in the environment. Either way it is safe to re-run.
set -euo pipefail

HOST=clock.cartercole.net
DISTRIBUTION=EM145PSSAP954

root=$(cd "$(dirname "$0")/.." && pwd)
stage=$(mktemp -d)
trap 'rm -rf "$stage"' EXIT

# web/ is the site plus the tooling that builds and tests it; only the site ships
rsync -a --delete \
  --exclude 'test/' \
  --exclude 'build_docs.py' \
  --exclude 'package.json' \
  "$root/web/" "$stage/"

# Content-Type and Cache-Control are set at upload time: the distribution uses the
# managed CachingOptimized policy, which honours whatever the origin says. HTML must
# revalidate — a stale entry point pins every asset it references.
put() {  # <cache-control> <aws s3 sync filters...>
  local cache=$1; shift
  aws s3 sync "$stage" "s3://$HOST" --no-progress --cache-control "$cache" "$@"
}

put 'no-cache, must-revalidate' --exclude '*' --include '*.html' \
  --content-type 'text/html; charset=utf-8'
put 'public, max-age=86400' --exclude '*' --include '*.js' \
  --content-type 'text/javascript; charset=utf-8'
put 'public, max-age=86400' --exclude '*' --include '*.css' \
  --content-type 'text/css; charset=utf-8'
# anything else the site grows into — images, fonts — typed by the CLI's own table
put 'public, max-age=86400' --exclude '*.html' --exclude '*.js' --exclude '*.css'

# Prune explicitly rather than with `sync --delete`: on a fresh CI checkout every
# local mtime is newer than its object, so a second sync pass would re-upload the
# whole site with guessed headers and undo the work above.
keys=$(mktemp -d)
trap 'rm -rf "$stage" "$keys"' EXIT

( cd "$stage" && find . -type f | sed 's|^\./||' ) | sort > "$keys/local"
aws s3api list-objects-v2 --bucket "$HOST" --query 'Contents[].Key' --output text \
  | tr '\t' '\n' | sed -e '/^$/d' -e '/^None$/d' | sort > "$keys/remote"
comm -13 "$keys/local" "$keys/remote" | while read -r key; do
  echo "prune  $key"
  aws s3 rm "s3://$HOST/$key"
done

aws cloudfront create-invalidation \
  --distribution-id "$DISTRIBUTION" --paths '/*' \
  --query 'Invalidation.{Id:Id,Status:Status}' --output text

echo "done -> https://$HOST/"
