#!/bin/bash
#
# aws-methuselah.sh

virtualenv env
source env/bin/activate
pip install -r aws-methuselah-requirements.txt
python aws-methuselah.py $@
