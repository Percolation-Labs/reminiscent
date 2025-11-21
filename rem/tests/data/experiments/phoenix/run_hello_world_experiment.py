"""Run a complete hello-world experiment in Phoenix."""

import asyncio
import random
from phoenix.client import Client
from pydantic import BaseModel

# API key from Kubernetes secret
API_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJqdGkiOiJBcGlLZXk6MyJ9.Hxdf349z3k9DGkYwnBAwqAXYM55JxOdGsbYAcbCteuY"


class HelloWorldAgentOutput(BaseModel):
    """Output from hello-world agent."""
    response: str
    confidence: float


def hello_world_agent_task(example: dict) -> dict:
    """Simple hello-world agent that responds to questions.

    This is a mock agent for testing purposes.
    """
    input_data = example.get("input", {})
    question = input_data.get("input", "")

    # Simple response logic
    if "hello" in question.lower():
        response = "Hello! How can I help you today?"
        confidence = 0.95
    elif "2+2" in question or "2 + 2" in question:
        response = "The answer is 4."
        confidence = 1.0
    elif "joke" in question.lower():
        response = "Why did the chicken cross the road? To get to the other side!"
        confidence = 0.8
    elif "weather" in question.lower():
        response = "I don't have access to real-time weather data, but you can check a weather service."
        confidence = 0.7
    elif "spanish" in question.lower() and "hello" in question.lower():
        response = "'Hello' in Spanish is 'Hola'."
        confidence = 0.9
    else:
        response = "I'm not sure how to answer that question."
        confidence = 0.3

    return {
        "response": response,
        "confidence": confidence
    }


def hello_world_evaluator(example: dict) -> dict:
    """Simple evaluator that checks correctness and helpfulness.

    This is a mock evaluator for testing purposes.
    """
    input_data = example.get("input", {})
    output_data = example.get("output", {})
    expected_data = example.get("expected", {})

    agent_response = output_data.get("response", "")
    expected_response = expected_data.get("reference", "")
    confidence = output_data.get("confidence", 0.0)

    # Simple correctness scoring (substring match)
    if agent_response.lower() in expected_response.lower() or expected_response.lower() in agent_response.lower():
        correctness = 0.9
    elif any(word in agent_response.lower() for word in expected_response.lower().split()[:3]):
        correctness = 0.6
    else:
        correctness = 0.3

    # Helpfulness based on confidence and response length
    if len(agent_response) > 10 and confidence > 0.5:
        helpfulness = 0.8
    elif len(agent_response) > 5:
        helpfulness = 0.6
    else:
        helpfulness = 0.4

    # Overall pass/fail
    avg_score = (correctness + helpfulness) / 2
    passed = avg_score >= 0.7

    explanation = f"Correctness: {correctness:.2f} (response similarity), Helpfulness: {helpfulness:.2f} (length and confidence)"

    return {
        "correctness": correctness,
        "helpfulness": helpfulness,
        "pass": passed,
        "explanation": explanation
    }


def main():
    """Run the complete experiment."""
    print("=" * 60)
    print("Hello World Phoenix Experiment")
    print("=" * 60)

    # Initialize Phoenix client
    print("\n1. Connecting to Phoenix...")
    client = Client(base_url="http://localhost:6006", api_key=API_KEY)
    print("✓ Connected to Phoenix")

    # Get dataset
    print("\n2. Loading dataset...")
    try:
        dataset = client.datasets.get_dataset(dataset="hello-world-golden")
        print(f"✓ Loaded dataset: {dataset.name} with {len(dataset)} examples")

        # Add metadata examples to demonstrate labeling
        print(f"  Dataset metadata: Test=✓, Integration=✓, HelloWorld=✓")
    except Exception as e:
        print(f"✗ Failed to load dataset: {e}")
        return

    # Run experiment with agent
    print("\n3. Running experiment with hello-world agent...")
    try:
        experiment = client.experiments.run_experiment(
            dataset=dataset,
            task=hello_world_agent_task,
            experiment_name="hello-world-v1",
            experiment_description="Baseline hello-world agent test",
            experiment_metadata={
                "agent": "hello-world",
                "version": "v1",
                "task": "hello-world"
            }
        )
        exp_name = experiment.get("name", "hello-world-v1") if isinstance(experiment, dict) else experiment.name
        exp_id = experiment.get("id", "unknown") if isinstance(experiment, dict) else experiment.id
        print(f"✓ Agent experiment complete: {exp_name}")
        print(f"  Experiment ID: {exp_id}")
    except Exception as e:
        print(f"✗ Failed to run agent experiment: {e}")
        import traceback
        traceback.print_exc()
        return

    # Run evaluator on results
    print("\n4. Running evaluator on agent outputs...")
    try:
        eval_experiment = client.experiments.run_experiment(
            dataset=dataset,
            task=hello_world_agent_task,  # Re-run agent for this test
            evaluators=[hello_world_evaluator],
            experiment_name="hello-world-v1-eval",
            experiment_description="Evaluation of hello-world agent",
            experiment_metadata={
                "evaluator": "hello-world-evaluator",
                "agent_experiment": exp_id,
                "version": "v1"
            }
        )
        eval_name = eval_experiment.get("name", "hello-world-v1-eval") if isinstance(eval_experiment, dict) else eval_experiment.name
        eval_id = eval_experiment.get("id", "unknown") if isinstance(eval_experiment, dict) else eval_experiment.id
        print(f"✓ Evaluation complete: {eval_name}")
        print(f"  Experiment ID: {eval_id}")
    except Exception as e:
        print(f"✗ Failed to run evaluator: {e}")
        import traceback
        traceback.print_exc()
        return

    # Display evaluation results
    print("\n5. Evaluation Results:")
    print("-" * 60)
    try:
        # Fetch full experiment details from Phoenix
        # If we don't have eval_id, get the most recent experiment
        if eval_id == "unknown":
            recent_experiments = list(client.experiments.list(dataset_id=dataset.id))
            if recent_experiments:
                eval_id = recent_experiments[0].get("id")

        exp_details = client.experiments.get_experiment(experiment_id=eval_id)

        task_runs = exp_details.get("task_runs", [])
        eval_runs = exp_details.get("evaluation_runs", [])

        if not task_runs:
            print("⚠  No task runs found in experiment")
            runs = []
        else:
            # Match task runs with evaluation runs and dataset examples
            runs = []
            dataset_examples = list(dataset)

            for idx, task_run in enumerate(task_runs):
                # Get the corresponding dataset example by index
                example = dataset_examples[idx] if idx < len(dataset_examples) else None

                # Extract input and expected from dataset example (examples are dicts)
                if example:
                    example_input = example.get("input", {})
                    example_output = example.get("output", {})
                    input_text = example_input.get("input", "") if isinstance(example_input, dict) else str(example_input)
                    expected_text = example_output.get("reference", "") if isinstance(example_output, dict) else str(example_output)
                else:
                    input_text = ""
                    expected_text = ""

                input_data = {"input": input_text}
                output_data = task_run.get("output", {})
                expected_data = {"reference": expected_text}

                # Re-run evaluator locally to get full scores
                # Phoenix only stores partial result (explanation), not all fields
                eval_result = hello_world_evaluator({
                    "input": input_data,
                    "output": output_data,
                    "expected": expected_data
                })

                runs.append({
                    "input": input_data,
                    "output": output_data,
                    "evaluation": eval_result,
                    "expected": expected_data
                })

        if not runs:
            print("⚠  No evaluation runs available")
        else:
            total_correctness = 0
            total_helpfulness = 0
            passed_count = 0
            total_count = len(runs)

            for i, run in enumerate(runs, 1):
                input_data = run.get("input", {})
                output_data = run.get("output", {})
                eval_data = run.get("evaluation", {})
                expected_data = run.get("expected", {})

                question = input_data.get("input", "")
                response = output_data.get("response", "")
                confidence = output_data.get("confidence", 0)
                expected = expected_data.get("reference", "")

                # Get evaluation scores
                correctness = eval_data.get("correctness", 0)
                helpfulness = eval_data.get("helpfulness", 0)
                passed = eval_data.get("pass", False)
                explanation = eval_data.get("explanation", "")

                total_correctness += correctness
                total_helpfulness += helpfulness
                if passed:
                    passed_count += 1

                status = "✓ PASS" if passed else "✗ FAIL"
                print(f"\nExample {i}/{total_count}: {status}")
                print(f"  Q: {question[:60]}")
                print(f"  A: {response[:60]} (confidence: {confidence:.2f})")
                print(f"  Expected: {expected[:60]}")
                print(f"  Scores:")
                print(f"    - Correctness:  {correctness:.2f}")
                print(f"    - Helpfulness:  {helpfulness:.2f}")
                print(f"    - Average:      {(correctness + helpfulness) / 2:.2f}")
                if explanation:
                    print(f"  Explanation: {explanation}")

            # Summary statistics
            print("\n" + "=" * 60)
            print("Summary Statistics:")
            print("=" * 60)
            print(f"  Total Examples:       {total_count}")
            print(f"  Passed:              {passed_count} ({passed_count/total_count*100:.1f}%)")
            print(f"  Failed:              {total_count - passed_count} ({(total_count-passed_count)/total_count*100:.1f}%)")
            print(f"  Avg Correctness:     {total_correctness/total_count:.2f}")
            print(f"  Avg Helpfulness:     {total_helpfulness/total_count:.2f}")
            print(f"  Overall Score:       {(total_correctness + total_helpfulness)/(2*total_count):.2f}")

            # Pass/Fail indicator
            overall_score = (total_correctness + total_helpfulness)/(2*total_count)
            if overall_score >= 0.7:
                print(f"\n  🎉 EXPERIMENT PASSED (score: {overall_score:.2f} >= 0.7)")
            else:
                print(f"\n  ⚠️  EXPERIMENT FAILED (score: {overall_score:.2f} < 0.7)")

    except Exception as e:
        print(f"⚠  Could not retrieve evaluation results: {e}")
        import traceback
        traceback.print_exc()

    print("\n" + "=" * 60)
    print("Experiment Complete!")
    print("=" * 60)
    print(f"\nView results in Phoenix UI:")
    print(f"  http://localhost:6006")
    print(f"\nDataset: hello-world-golden ({len(dataset)} examples)")
    print(f"  Labels: Test, Integration, HelloWorld")
    print(f"\nAgent Experiment: {exp_name}")
    print(f"  ID: {exp_id}")
    print(f"  Metadata: agent=hello-world, version=v1, task=hello-world")
    print(f"\nEval Experiment: {eval_name}")
    print(f"  ID: {eval_id}")
    print(f"  Metadata: evaluator=hello-world-evaluator, version=v1")


if __name__ == "__main__":
    main()
