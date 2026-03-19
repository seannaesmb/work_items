#!/bin/bash
# Run using ./enforce.sh tag=""
ansible-playbook -e "$1" -v -b -i  /dev/null site.yml >&2
