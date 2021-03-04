#!/bin/bash
#
# aws-methuselah.sh

pipenv install

pipenv run python3 aws-methuselah.py "$@"
