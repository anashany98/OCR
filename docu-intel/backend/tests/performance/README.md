# Performance Test Suite - Docu-Intel

## Overview

Load testing scripts to measure Docu-Intel performance.
Run AFTER starting the application with Docker Compose.

## Prerequisites

`ash
pip install requests python-dotenv tqdm
`

## Running Tests

`ash
# Start the application first
cd docu-intel
docker compose up --build

# In another terminal, run tests
cd backend/tests/performance
python test_ingestion.py      # Test 1: Document ingestion
python test_search.py         # Test 2: Search endpoints
python test_api_sustained.py  # Test 3: Sustained API load
python run_all.py             # Run all tests and generate report
`

## Test Results

Results are saved to results/ directory with timestamps.
