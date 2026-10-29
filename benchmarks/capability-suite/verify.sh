#!/bin/zsh
# usage: verify.sh <task>...  each task's hidden tests must FAIL on repo/ and PASS on its reference.
HERE=${0:A:h}
SCRATCH=${DISPATCH_STORAGE_ROOT:-$HOME/.cache/dispatch}/scratch
mkdir -p $SCRATCH
if [[ ! -d $HERE/ref-solutions ]]; then
  echo "verify.sh: ref-solutions/ is not in this checkout (kept private); checking only that hidden tests FAIL on repo/" >&2
  MODES=(start)
else
  MODES=(start ref)
fi
for t in "$@"; do
  for mode in $MODES; do
    W=$(mktemp -d $SCRATCH/capverify.XXXX)
    if [[ $mode == start ]]; then cp -R $HERE/tasks/$t/repo/. $W/; else cp -R $HERE/ref-solutions/$t/. $W/; fi
    cp $HERE/tasks/$t/hidden/* $W/
    (cd $W && python3 -m pytest -q -p no:cacheprovider hidden_*.py > $W.log 2>&1); rc=$?
    echo "$t $mode rc=$rc :: $(tail -1 $W.log)"
    rm -rf $W $W.log
  done
done
