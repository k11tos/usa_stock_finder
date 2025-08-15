#!/bin/bash

# USA Stock Finder Test Runner Script
# 다양한 테스트 시나리오를 실행할 수 있는 스크립트

set -e  # 에러 발생 시 스크립트 중단

# 색상 정의
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 로그 함수
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# 가상환경 활성화 확인
check_venv() {
    if [[ "$VIRTUAL_ENV" == "" ]]; then
        log_warning "가상환경이 활성화되지 않았습니다."
        if [ -d "env" ]; then
            log_info "가상환경을 활성화합니다..."
            source env/bin/activate
        else
            log_error "env 디렉토리를 찾을 수 없습니다."
            exit 1
        fi
    else
        log_success "가상환경이 활성화되었습니다: $VIRTUAL_ENV"
    fi
}

# 의존성 확인
check_dependencies() {
    log_info "의존성을 확인합니다..."

    if ! command -v python3 &> /dev/null; then
        log_error "python3가 설치되지 않았습니다."
        exit 1
    fi

    if ! python3 -c "import pytest" &> /dev/null; then
        log_error "pytest가 설치되지 않았습니다. requirements_dev.txt를 설치하세요."
        exit 1
    fi

    log_success "의존성 확인 완료"
}

# 전체 테스트 실행
run_all_tests() {
    log_info "전체 테스트를 실행합니다..."
    python3 -m pytest --tb=short
}

# 단위 테스트만 실행
run_unit_tests() {
    log_info "단위 테스트만 실행합니다..."
    python3 -m pytest tests/ -v --ignore=tests/test_integration/ -m "not integration"
}

# 통합 테스트만 실행
run_integration_tests() {
    log_info "통합 테스트만 실행합니다..."
    python3 -m pytest tests/test_integration/ -v -m "integration"
}

# 특정 테스트 파일 실행
run_specific_test() {
    local test_file="$1"
    if [ -z "$test_file" ]; then
        log_error "테스트 파일을 지정해주세요."
        echo "사용법: $0 specific <test_file>"
        exit 1
    fi

    if [ ! -f "$test_file" ]; then
        log_error "테스트 파일을 찾을 수 없습니다: $test_file"
        exit 1
    fi

    log_info "특정 테스트를 실행합니다: $test_file"
    python3 -m pytest "$test_file" -v
}

# 마커별 테스트 실행
run_tests_by_marker() {
    local marker="$1"
    if [ -z "$marker" ]; then
        log_error "마커를 지정해주세요."
        echo "사용 가능한 마커: unit, integration, fast, slow, error_handling, performance, memory, concurrent"
        exit 1
    fi

    log_info "마커 '$marker'로 테스트를 실행합니다..."
    python3 -m pytest -v -m "$marker"
}

# 커버리지 측정과 함께 실행
run_tests_with_coverage() {
    log_info "커버리지 측정과 함께 테스트를 실행합니다..."

    # coverage 패키지 확인
    if ! python3 -c "import coverage" &> /dev/null; then
        log_warning "coverage 패키지가 설치되지 않았습니다. 설치합니다..."
        pip install coverage
    fi

    python3 -m pytest --cov=. --cov-report=html --cov-report=term-missing
    log_success "커버리지 리포트가 htmlcov/ 디렉토리에 생성되었습니다."
}

# 성능 테스트 실행
run_performance_tests() {
    log_info "성능 테스트를 실행합니다..."
    python3 -m pytest -v -m "performance"
}

# 빠른 테스트 실행 (느린 테스트 제외)
run_fast_tests() {
    log_info "빠른 테스트를 실행합니다 (느린 테스트 제외)..."
    python3 -m pytest -v -m "fast" -m "not slow"
}

# 에러 처리 테스트 실행
run_error_handling_tests() {
    log_info "에러 처리 테스트를 실행합니다..."
    python3 -m pytest -v -m "error_handling"
}

# 병렬 테스트 실행
run_parallel_tests() {
    log_info "병렬로 테스트를 실행합니다..."

    # pytest-xdist 패키지 확인
    if ! python3 -c "import xdist" &> /dev/null; then
        log_warning "pytest-xdist 패키지가 설치되지 않았습니다. 설치합니다..."
        pip install pytest-xdist
    fi

    python3 -m pytest -n auto --dist=loadfile
}

# 테스트 정리
cleanup_tests() {
    log_info "테스트 캐시를 정리합니다..."
    python3 -m pytest --cache-clear
    rm -rf .pytest_cache/
    rm -rf htmlcov/
    rm -rf .coverage
    log_success "테스트 정리 완료"
}

# 도움말 표시
show_help() {
    echo "USA Stock Finder Test Runner"
    echo ""
    echo "사용법: $0 <command> [options]"
    echo ""
    echo "명령어:"
    echo "  all                    전체 테스트 실행"
    echo "  unit                   단위 테스트만 실행"
    echo "  integration            통합 테스트만 실행"
    echo "  specific <file>        특정 테스트 파일 실행"
    echo "  marker <marker>        마커별 테스트 실행"
    echo "  coverage               커버리지 측정과 함께 실행"
    echo "  performance            성능 테스트 실행"
    echo "  fast                   빠른 테스트 실행"
    echo "  error-handling         에러 처리 테스트 실행"
    echo "  parallel               병렬 테스트 실행"
    echo "  cleanup                테스트 캐시 정리"
    echo "  help                   이 도움말 표시"
    echo ""
    echo "마커 옵션:"
    echo "  unit, integration, fast, slow, error_handling, performance, memory, concurrent"
    echo ""
    echo "예시:"
    echo "  $0 all                 # 전체 테스트 실행"
    echo "  $0 unit                # 단위 테스트만 실행"
    echo "  $0 marker fast         # 빠른 테스트만 실행"
    echo "  $0 specific tests/test_file_utils.py  # 특정 파일 테스트"
}

# 메인 실행 로직
main() {
    local command="$1"

    case "$command" in
        "all")
            check_venv
            check_dependencies
            run_all_tests
            ;;
        "unit")
            check_venv
            check_dependencies
            run_unit_tests
            ;;
        "integration")
            check_venv
            check_dependencies
            run_integration_tests
            ;;
        "specific")
            check_venv
            check_dependencies
            run_specific_test "$2"
            ;;
        "marker")
            check_venv
            check_dependencies
            run_tests_by_marker "$2"
            ;;
        "coverage")
            check_venv
            check_dependencies
            run_tests_with_coverage
            ;;
        "performance")
            check_venv
            check_dependencies
            run_performance_tests
            ;;
        "fast")
            check_venv
            check_dependencies
            run_fast_tests
            ;;
        "error-handling")
            check_venv
            check_dependencies
            run_error_handling_tests
            ;;
        "parallel")
            check_venv
            check_dependencies
            run_parallel_tests
            ;;
        "cleanup")
            cleanup_tests
            ;;
        "help"|"--help"|"-h"|"")
            show_help
            ;;
        *)
            log_error "알 수 없는 명령어: $command"
            show_help
            exit 1
            ;;
    esac
}

# 스크립트 실행
main "$@"
