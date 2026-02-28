"""Model Benchmark Suite for Browser Agent.

Evaluates models on standardized navigation tasks to measure:
- Accuracy: Task completion success rate
- Speed: Time to complete, tokens used
- Efficiency: Steps taken, actions per goal

Usage:
    python -m browser_agent.benchmark --models "qwen2.5:7b,qwen2.5:14b,qwen2.5:32b"
    python -m browser_agent.benchmark --models "qwen2.5:14b" --tasks "navigation"
    python -m browser_agent.benchmark --list-tasks
"""

import asyncio
import argparse
import json
import logging
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import List, Dict, Optional, Any
from pathlib import Path

from playwright.async_api import async_playwright, Page

from .core.navigator import Navigator
from .core.browser import BrowserController, BrowserTools

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


@dataclass
class TestCase:
    """A single test case for benchmarking."""
    id: str
    name: str
    category: str  # navigation, search, interaction, multi-step
    description: str
    start_url: str
    goal: str
    success_criteria: List[str]  # URL patterns or page content to verify
    max_steps: int = 15
    timeout: int = 120
    difficulty: str = "medium"  # easy, medium, hard


@dataclass
class TestResult:
    """Result of running a single test case."""
    test_id: str
    model: str
    success: bool
    time_seconds: float
    steps_taken: int
    tokens_used: int
    final_url: str
    summary: str
    error: Optional[str] = None
    visited_urls: List[str] = field(default_factory=list)


@dataclass
class BenchmarkResult:
    """Aggregated results for a model across all tests."""
    model: str
    total_tests: int
    passed: int
    failed: int
    success_rate: float
    avg_time_seconds: float
    avg_steps: float
    total_tokens: int
    avg_tokens_per_test: float
    results_by_category: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    individual_results: List[TestResult] = field(default_factory=list)


# =============================================================================
# TEST CASES
# =============================================================================

BENCHMARK_TESTS: List[TestCase] = [
    # --- NAVIGATION (Simple goto and verify) ---
    TestCase(
        id="nav-001",
        name="Navigate to CNN homepage",
        category="navigation",
        description="Go to CNN and verify we're on the news site",
        start_url="about:blank",
        goal="Go to cnn.com and confirm you're on the CNN homepage",
        success_criteria=["cnn.com"],
        max_steps=5,
        timeout=60,
        difficulty="easy",
    ),
    TestCase(
        id="nav-002",
        name="Navigate to GitHub",
        category="navigation",
        description="Go to GitHub homepage",
        start_url="about:blank",
        goal="Navigate to github.com",
        success_criteria=["github.com"],
        max_steps=5,
        timeout=60,
        difficulty="easy",
    ),
    TestCase(
        id="nav-003",
        name="Navigate to Wikipedia",
        category="navigation",
        description="Go to Wikipedia and verify",
        start_url="about:blank",
        goal="Go to wikipedia.org",
        success_criteria=["wikipedia.org"],
        max_steps=5,
        timeout=60,
        difficulty="easy",
    ),

    # --- SEARCH (Find content on a page) ---
    TestCase(
        id="search-001",
        name="Find Python on Wikipedia",
        category="search",
        description="Navigate to Wikipedia and find the Python programming language page",
        start_url="https://wikipedia.org",
        goal="Search for 'Python programming language' on Wikipedia and go to that article",
        success_criteria=["wikipedia.org/wiki/Python"],
        max_steps=10,
        timeout=90,
        difficulty="medium",
    ),
    TestCase(
        id="search-002",
        name="Find trending repos on GitHub",
        category="search",
        description="Navigate to GitHub trending page",
        start_url="https://github.com",
        goal="Find the trending repositories page on GitHub",
        success_criteria=["github.com/trending"],
        max_steps=10,
        timeout=90,
        difficulty="medium",
    ),
    TestCase(
        id="search-003",
        name="Find a news article",
        category="search",
        description="Go to BBC and find any news article",
        start_url="https://bbc.com",
        goal="Go to BBC News and click on any news article to read it",
        success_criteria=["bbc.com/news/", "bbc.co.uk/news/"],
        max_steps=10,
        timeout=90,
        difficulty="medium",
    ),

    # --- INTERACTION (Click, type, form interactions) ---
    TestCase(
        id="interact-001",
        name="GitHub search box",
        category="interaction",
        description="Use GitHub's search functionality",
        start_url="https://github.com",
        goal="Use the search box on GitHub to search for 'langchain' and view the results",
        success_criteria=["github.com/search", "q=langchain"],
        max_steps=12,
        timeout=120,
        difficulty="medium",
    ),
    TestCase(
        id="interact-002",
        name="Wikipedia search",
        category="interaction",
        description="Use Wikipedia's search box",
        start_url="https://wikipedia.org",
        goal="Search Wikipedia for 'artificial intelligence' using the search box",
        success_criteria=["wikipedia.org/wiki/Artificial_intelligence", "search=artificial"],
        max_steps=12,
        timeout=120,
        difficulty="medium",
    ),

    # --- MULTI-STEP (Complex sequences) ---
    TestCase(
        id="multi-001",
        name="GitHub repo exploration",
        category="multi-step",
        description="Navigate through GitHub to find specific content",
        start_url="https://github.com",
        goal="Go to GitHub, find the trending Python repositories, and click on one of them",
        success_criteria=["github.com/"],  # Should be on a repo page
        max_steps=15,
        timeout=150,
        difficulty="hard",
    ),
    TestCase(
        id="multi-002",
        name="News article reading",
        category="multi-step",
        description="Navigate to news site and read an article",
        start_url="https://reuters.com",
        goal="Go to Reuters, find a technology news article, and scroll through it",
        success_criteria=["reuters.com"],
        max_steps=15,
        timeout=150,
        difficulty="hard",
    ),
    TestCase(
        id="multi-003",
        name="Stack Overflow question",
        category="multi-step",
        description="Find a specific type of question on Stack Overflow",
        start_url="https://stackoverflow.com",
        goal="Go to Stack Overflow and find a question about Python async/await",
        success_criteria=["stackoverflow.com/questions/"],
        max_steps=15,
        timeout=150,
        difficulty="hard",
    ),
]


def get_tests_by_category(category: str = None) -> List[TestCase]:
    """Get tests filtered by category."""
    if category is None:
        return BENCHMARK_TESTS
    return [t for t in BENCHMARK_TESTS if t.category == category]


def list_tests():
    """Print available test cases."""
    print("\n" + "=" * 70)
    print("AVAILABLE BENCHMARK TESTS")
    print("=" * 70)

    categories = {}
    for test in BENCHMARK_TESTS:
        if test.category not in categories:
            categories[test.category] = []
        categories[test.category].append(test)

    for category, tests in categories.items():
        print(f"\n[{category.upper()}]")
        for test in tests:
            print(f"  {test.id}: {test.name} ({test.difficulty})")
            print(f"       {test.description}")


# =============================================================================
# BENCHMARK RUNNER
# =============================================================================

class BenchmarkRunner:
    """Runs benchmark tests against different models."""

    def __init__(
        self,
        models: List[str],
        tests: List[TestCase] = None,
        headless: bool = True,
        output_dir: str = "./benchmark_results",
    ):
        self.models = models
        self.tests = tests or BENCHMARK_TESTS
        self.headless = headless
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)

    def check_success(self, test: TestCase, final_url: str, visited_urls: List[str]) -> bool:
        """Check if test success criteria are met."""
        all_urls = visited_urls + [final_url]

        for criterion in test.success_criteria:
            # Check if any visited URL contains the criterion
            if any(criterion.lower() in url.lower() for url in all_urls):
                return True

        return False

    async def run_single_test(
        self,
        model: str,
        test: TestCase,
        page: Page,
    ) -> TestResult:
        """Run a single test case."""
        logger.info(f"  Running: {test.id} - {test.name}")

        # Create navigator with the model
        navigator = Navigator(model=model)

        start_time = time.time()
        error = None
        success = False
        summary = ""
        visited_urls = []
        steps_taken = 0

        try:
            # Navigate to start URL
            if test.start_url != "about:blank":
                await page.goto(test.start_url, timeout=30000)
                await page.wait_for_load_state("domcontentloaded", timeout=15000)

            # Run navigation
            nav_success, summary, browser_tools = await navigator.navigate(
                page=page,
                goal=test.goal,
                max_steps=test.max_steps,
                timeout=test.timeout,
            )

            visited_urls = browser_tools.visited_urls
            steps_taken = browser_tools.action_count

            # Check success criteria
            final_url = page.url
            success = self.check_success(test, final_url, visited_urls)

            if not success and nav_success:
                # Navigator thought it succeeded but criteria not met
                summary = f"Criteria not met. Final URL: {final_url}"

        except asyncio.TimeoutError:
            error = "Timeout"
            summary = "Test timed out"
        except Exception as e:
            error = str(e)[:100]
            summary = f"Error: {error}"

        elapsed = time.time() - start_time

        # Get token stats
        tokens_used = navigator.token_tracker.total_tokens if hasattr(navigator, 'token_tracker') else 0

        result = TestResult(
            test_id=test.id,
            model=model,
            success=success,
            time_seconds=round(elapsed, 2),
            steps_taken=steps_taken,
            tokens_used=tokens_used,
            final_url=page.url if page else "",
            summary=summary[:200],
            error=error,
            visited_urls=visited_urls,
        )

        status = "✅ PASS" if success else "❌ FAIL"
        logger.info(f"    {status} ({elapsed:.1f}s, {steps_taken} steps)")

        return result

    async def run_model_benchmark(self, model: str) -> BenchmarkResult:
        """Run all tests for a single model."""
        logger.info(f"\n{'='*60}")
        logger.info(f"BENCHMARKING MODEL: {model}")
        logger.info(f"{'='*60}")

        results: List[TestResult] = []

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=self.headless)
            context = await browser.new_context(
                viewport={"width": 1280, "height": 720},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/121.0.0.0",
            )

            for test in self.tests:
                page = await context.new_page()
                try:
                    result = await self.run_single_test(model, test, page)
                    results.append(result)
                finally:
                    await page.close()

                # Small delay between tests
                await asyncio.sleep(2)

            await browser.close()

        # Aggregate results
        passed = sum(1 for r in results if r.success)
        failed = len(results) - passed
        total_time = sum(r.time_seconds for r in results)
        total_steps = sum(r.steps_taken for r in results)
        total_tokens = sum(r.tokens_used for r in results)

        # Results by category
        categories = {}
        for test in self.tests:
            if test.category not in categories:
                categories[test.category] = {"total": 0, "passed": 0, "avg_time": 0, "times": []}
            categories[test.category]["total"] += 1

        for result in results:
            test = next(t for t in self.tests if t.id == result.test_id)
            cat = test.category
            if result.success:
                categories[cat]["passed"] += 1
            categories[cat]["times"].append(result.time_seconds)

        for cat in categories:
            times = categories[cat]["times"]
            categories[cat]["avg_time"] = sum(times) / len(times) if times else 0
            categories[cat]["success_rate"] = categories[cat]["passed"] / categories[cat]["total"]
            del categories[cat]["times"]  # Clean up

        return BenchmarkResult(
            model=model,
            total_tests=len(results),
            passed=passed,
            failed=failed,
            success_rate=round(passed / len(results) * 100, 1) if results else 0,
            avg_time_seconds=round(total_time / len(results), 2) if results else 0,
            avg_steps=round(total_steps / len(results), 1) if results else 0,
            total_tokens=total_tokens,
            avg_tokens_per_test=round(total_tokens / len(results), 0) if results else 0,
            results_by_category=categories,
            individual_results=results,
        )

    async def run_all(self) -> Dict[str, BenchmarkResult]:
        """Run benchmarks for all models."""
        all_results = {}

        for model in self.models:
            result = await self.run_model_benchmark(model)
            all_results[model] = result

        return all_results

    def print_summary(self, results: Dict[str, BenchmarkResult]):
        """Print a summary comparison of all models."""
        print("\n" + "=" * 80)
        print("BENCHMARK SUMMARY")
        print("=" * 80)

        # Header
        print(f"\n{'Model':<30} {'Success':<10} {'Avg Time':<12} {'Avg Steps':<12} {'Tokens':<12}")
        print("-" * 80)

        # Sort by success rate, then by time
        sorted_results = sorted(
            results.values(),
            key=lambda r: (-r.success_rate, r.avg_time_seconds)
        )

        for r in sorted_results:
            print(f"{r.model:<30} {r.success_rate:>6.1f}%    {r.avg_time_seconds:>8.1f}s    {r.avg_steps:>8.1f}      {r.avg_tokens_per_test:>8.0f}")

        # Category breakdown
        print("\n" + "-" * 80)
        print("BY CATEGORY:")
        print("-" * 80)

        categories = set()
        for r in results.values():
            categories.update(r.results_by_category.keys())

        for category in sorted(categories):
            print(f"\n  [{category.upper()}]")
            for model, r in results.items():
                if category in r.results_by_category:
                    cat_data = r.results_by_category[category]
                    print(f"    {model:<26} {cat_data['success_rate']*100:>5.1f}% ({cat_data['passed']}/{cat_data['total']})  avg: {cat_data['avg_time']:.1f}s")

        # Recommendation
        print("\n" + "=" * 80)
        print("RECOMMENDATION:")
        print("=" * 80)

        if sorted_results:
            best = sorted_results[0]
            fastest = min(results.values(), key=lambda r: r.avg_time_seconds)
            most_efficient = min(results.values(), key=lambda r: r.avg_tokens_per_test if r.avg_tokens_per_test > 0 else float('inf'))

            print(f"\n  Best Overall:     {best.model} ({best.success_rate}% success)")
            print(f"  Fastest:          {fastest.model} ({fastest.avg_time_seconds}s avg)")
            print(f"  Most Efficient:   {most_efficient.model} ({most_efficient.avg_tokens_per_test:.0f} tokens/test)")

            # Speed/Accuracy tradeoff
            print("\n  Speed/Accuracy Tradeoff:")
            for r in sorted_results:
                score = r.success_rate - (r.avg_time_seconds * 0.5)  # Penalize slower models
                print(f"    {r.model:<26} score: {score:.1f}")

    def save_results(self, results: Dict[str, BenchmarkResult]):
        """Save results to JSON file."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = self.output_dir / f"benchmark_{timestamp}.json"

        # Convert to serializable format
        data = {
            "timestamp": timestamp,
            "models": self.models,
            "test_count": len(self.tests),
            "results": {
                model: {
                    **asdict(result),
                    "individual_results": [asdict(r) for r in result.individual_results]
                }
                for model, result in results.items()
            }
        }

        with open(output_file, "w") as f:
            json.dump(data, f, indent=2)

        logger.info(f"\nResults saved to: {output_file}")


# =============================================================================
# CLI
# =============================================================================

async def main():
    parser = argparse.ArgumentParser(description="Benchmark browser agent models")
    parser.add_argument(
        "--models",
        type=str,
        default="ollama/qwen2.5:7b,ollama/qwen2.5:14b",
        help="Comma-separated list of models to test",
    )
    parser.add_argument(
        "--category",
        type=str,
        choices=["navigation", "search", "interaction", "multi-step"],
        help="Only run tests in this category",
    )
    parser.add_argument(
        "--test-ids",
        type=str,
        help="Comma-separated list of specific test IDs to run",
    )
    parser.add_argument(
        "--list-tasks",
        action="store_true",
        help="List available test cases and exit",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        default=True,
        help="Run browser in headless mode",
    )
    parser.add_argument(
        "--no-headless",
        action="store_true",
        help="Run browser with visible window",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="./benchmark_results",
        help="Directory to save results",
    )

    args = parser.parse_args()

    if args.list_tasks:
        list_tests()
        return

    models = [m.strip() for m in args.models.split(",")]

    # Filter tests
    tests = BENCHMARK_TESTS
    if args.category:
        tests = get_tests_by_category(args.category)
    if args.test_ids:
        test_ids = [t.strip() for t in args.test_ids.split(",")]
        tests = [t for t in tests if t.id in test_ids]

    if not tests:
        print("No tests match the specified criteria")
        return

    print(f"\nRunning {len(tests)} tests across {len(models)} models...")

    runner = BenchmarkRunner(
        models=models,
        tests=tests,
        headless=not args.no_headless,
        output_dir=args.output_dir,
    )

    results = await runner.run_all()
    runner.print_summary(results)
    runner.save_results(results)


if __name__ == "__main__":
    asyncio.run(main())
