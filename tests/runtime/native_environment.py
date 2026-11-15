"""Selected distribution/compiler boundary inside declared native tool roots."""

DISTRIBUTION = 'ubuntu/26.04'
LLVM_MAJOR = 18
LLVM_VERSION = '18.1.8'


def build_prefix():
    # Check the mounted declared root, rather than the container that assembled it.
    return ('set -euo pipefail\n'
            f'export CC=clang-{LLVM_MAJOR} CXX=clang++-{LLVM_MAJOR}\n'
            '. /etc/os-release\n'
            f'test "$ID/$VERSION_ID" = {DISTRIBUTION}\n'
            f'clang-{LLVM_MAJOR} --version | grep -F "clang version {LLVM_VERSION}"\n')
