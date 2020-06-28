#!/bin/bash
#
# aws-methuselah.sh

virtualenv env

# shellcheck disable=SC1091
source env/bin/activate

pip install -r aws-methuselah-requirements.txt

python aws-methuselah.py "$@"
