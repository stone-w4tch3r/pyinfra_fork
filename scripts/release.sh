#!/bin/bash

set -euo pipefail

VERSION="0.1.0"
MAJOR_BRANCH="2.x"

echo "# Releasing pyinfra v${VERSION} (branch ${MAJOR_BRANCH})"

#echo "# Running tests..."
#pytest

#echo "# Git tag & push..."
#git tag -a "v$VERSION" -m "v$VERSION"
#git push --tags

echo "Clear existing build/dist..."
rm -rf build/* dist/*
echo "Build source and wheel packages..."
python setup.py sdist bdist_wheel
echo "Upload w/Twine..."
twine upload dist/*

echo "# All done!"


