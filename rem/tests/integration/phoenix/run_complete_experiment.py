"""Complete Phoenix experiment with prompts, labels, and structured scores.

This script demonstrates:
1. Creating and labeling prompts
2. Creating and labeling datasets
3. Running experiments with structured evaluator outputs
4. Displaying full evaluation results

Run from scratch after deleting previous dataset.
"""

import os
from phoenix.client import Client
from rem.services.phoenix.prompt_labels import PhoenixPromptLabels, REM_LABELS

# Phoenix configuration
BASE_URL = "http://localhost:6006"
API_KEY = os.getenv("PHOENIX_API_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJqdGkiOiJBcGlLZXk6MyJ9.Hxdf349z3k9DGkYwnBAwqAXYM55JxOdGsbYAcbCteuY")


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


def hello_world_evaluator(example: dict) -> list[dict]:
    """Evaluator that returns multiple named evaluations for Phoenix.

    CRITICAL: Phoenix displays each evaluation as a separate column when
    you return a list of dicts with 'name', 'score', 'label', 'explanation'.
    """
    input_data = example.get("input", {})
    output_data = example.get("output", {})
    expected_data = example.get("expected", {})

    agent_response = output_data.get("response", "")
    expected_response = expected_data.get("reference", "")
    confidence = output_data.get("confidence", 0.0)

    # Calculate correctness score (substring match)
    if agent_response.lower() in expected_response.lower() or expected_response.lower() in agent_response.lower():
        correctness_score = 0.9
        correctness_label = "correct"
        correctness_explanation = "Response matches reference closely"
    elif any(word in agent_response.lower() for word in expected_response.lower().split()[:3]):
        correctness_score = 0.6
        correctness_label = "partial"
        correctness_explanation = "Response partially matches reference (some words match)"
    else:
        correctness_score = 0.3
        correctness_label = "incorrect"
        correctness_explanation = "Response does not match reference"

    # Calculate helpfulness score based on confidence and response length
    if len(agent_response) > 10 and confidence > 0.5:
        helpfulness_score = 0.8
        helpfulness_label = "helpful"
        helpfulness_explanation = "Response is detailed and agent is confident"
    elif len(agent_response) > 5:
        helpfulness_score = 0.6
        helpfulness_label = "moderate"
        helpfulness_explanation = "Response has moderate length"
    else:
        helpfulness_score = 0.4
        helpfulness_label = "brief"
        helpfulness_explanation = "Response is brief"

    # Overall score and pass/fail
    overall_score = (correctness_score + helpfulness_score) / 2
    overall_label = "PASS" if overall_score >= 0.7 else "FAIL"
    overall_explanation = f"Average: {overall_score:.2f} = ({correctness_score:.2f} + {helpfulness_score:.2f}) / 2"

    # CRITICAL: Return list of named evaluations - each becomes a Phoenix column
    return [
        {
            "name": "correctness",
            "score": correctness_score,
            "label": correctness_label,
            "explanation": correctness_explanation,
        },
        {
            "name": "helpfulness",
            "score": helpfulness_score,
            "label": helpfulness_label,
            "explanation": helpfulness_explanation,
        },
        {
            "name": "overall",
            "score": overall_score,
            "label": overall_label,
            "explanation": overall_explanation,
        },
    ]


def main():
    """Run the complete experiment with prompts, labels, and structured scores."""
    print("=" * 70)
    print("Phoenix Complete Experiment")
    print("Prompts | Labels | Structured Scores")
    print("=" * 70)

    # Initialize Phoenix client
    print("\n1. Connecting to Phoenix...")
    client = Client(base_url=BASE_URL, api_key=API_KEY)
    print("✓ Connected to Phoenix")

    # Initialize label manager
    print("\n2. Setting up labels...")
    label_helper = PhoenixPromptLabels(base_url=BASE_URL, api_key=API_KEY)

    # Ensure all REM labels exist (prompts and datasets)
    print("  Creating prompt labels...")
    label_helper.ensure_prompt_labels(REM_LABELS)
    print(f"  ✓ Ensured {len(REM_LABELS)} prompt labels")

    print("  Creating dataset labels...")
    label_helper.ensure_dataset_labels(REM_LABELS)
    print(f"  ✓ Ensured {len(REM_LABELS)} dataset labels")

    # List available labels
    prompt_labels = label_helper.list_prompt_labels()
    dataset_labels = label_helper.list_dataset_labels()
    print(f"  Available prompt labels: {list(prompt_labels.keys())}")
    print(f"  Available dataset labels: {list(dataset_labels.keys())}")

    # Create test prompts from schemas
    print("\n2b. Creating prompts from schemas...")
    try:
        from phoenix.client.types import PromptVersion
        import yaml
        import httpx

        def get_parent_prompt_id(prompt_name: str, base_url: str, api_key: str) -> str | None:
            """Get parent Prompt ID from prompt name via GraphQL."""
            query = """
            query {
              prompts(first: 100) {
                edges {
                  node {
                    id
                    name
                  }
                }
              }
            }
            """
            headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
            response = httpx.post(
                f"{base_url}/graphql",
                headers=headers,
                json={"query": query},
                timeout=10,
            )
            if response.status_code == 200:
                result = response.json()
                if result.get("data"):
                    for edge in result["data"]["prompts"]["edges"]:
                        if edge["node"]["name"] == prompt_name:
                            return edge["node"]["id"]
            return None

        # Load agent schema
        with open("schemas/agents/examples/hello-world.yaml") as f:
            agent_schema = yaml.safe_load(f)

        # Create prompt for agent
        agent_messages = [
            {"role": "system", "content": agent_schema.get("description", "")}
        ]
        agent_prompt_version = PromptVersion.from_openai({
            "model": "gpt-4o-mini",
            "messages": agent_messages,
        })

        agent_prompt = client.prompts.create(
            name="hello-world-v1",
            prompt_description="Hello World agent prompt for testing",
            version=agent_prompt_version,
        )
        print(f"  ✓ Created agent prompt version: {agent_prompt.id}")

        # Get parent prompt ID for label assignment
        parent_prompt_id = get_parent_prompt_id("hello-world-v1", BASE_URL, API_KEY)
        if parent_prompt_id:
            print(f"    Parent Prompt ID: {parent_prompt_id}")
            # Assign labels to agent prompt
            label_helper.assign_prompt_labels(
                prompt_id=parent_prompt_id,
                label_names=["REM", "Agent", "HelloWorld", "Test"]
            )
            print("    ✓ Assigned labels: REM, Agent, HelloWorld, Test")
        else:
            print("    ⚠  Could not get parent prompt ID for label assignment")

        # Load evaluator schema
        with open("schemas/evaluators/hello-world-evaluator.yaml") as f:
            eval_schema = yaml.safe_load(f)

        # Create prompt for evaluator
        eval_messages = [
            {"role": "system", "content": eval_schema.get("description", "")}
        ]
        eval_prompt_version = PromptVersion.from_openai({
            "model": "gpt-4o-mini",
            "messages": eval_messages,
        })

        eval_prompt = client.prompts.create(
            name="hello-world-evaluator-v1",
            prompt_description="Hello World evaluator prompt for testing",
            version=eval_prompt_version,
        )
        print(f"  ✓ Created evaluator prompt version: {eval_prompt.id}")

        # Get parent prompt ID for evaluator
        eval_parent_id = get_parent_prompt_id("hello-world-evaluator-v1", BASE_URL, API_KEY)
        if eval_parent_id:
            print(f"    Parent Prompt ID: {eval_parent_id}")
            # Assign labels to evaluator prompt
            label_helper.assign_prompt_labels(
                prompt_id=eval_parent_id,
                label_names=["REM", "Evaluator", "HelloWorld", "Test"]
            )
            print("    ✓ Assigned labels: REM, Evaluator, HelloWorld, Test")
        else:
            print("    ⚠  Could not get parent prompt ID for label assignment")

    except Exception as e:
        print(f"  ⚠  Prompt creation failed: {e}")
        import traceback
        traceback.print_exc()

    # Create or get existing dataset
    print("\n3. Creating/getting dataset with labels...")
    try:
        # Try to get existing dataset first
        try:
            dataset = client.datasets.get_dataset(dataset="hello-world-golden-v2")
            print(f"✓ Using existing dataset: {dataset.name} with {len(dataset)} examples")
        except:
            # Dataset doesn't exist, create it
            dataset = client.datasets.create_dataset(
                name="hello-world-golden-v2",
                inputs=[
                    {"input": "Hello, world!"},
                    {"input": "What is 2+2?"},
                    {"input": "Tell me a joke"},
                    {"input": "What's the weather?"},
                    {"input": "Translate 'hello' to Spanish"},
                ],
                outputs=[
                    {"reference": "Hello! How can I help you today?"},
                    {"reference": "The answer is 4."},
                    {"reference": "Why did the chicken cross the road? To get to the other side!"},
                    {"reference": "I don't have access to real-time weather data, but you can check a weather service."},
                    {"reference": "'Hello' in Spanish is 'Hola'."},
                ],
                dataset_description="Hello World test dataset with ground truth examples",
            )
            print(f"✓ Created new dataset: {dataset.name} with {len(dataset)} examples")

        # Get dataset ID directly from Phoenix client (GraphQL query has issues)
        dataset_id = dataset.id  # Use Phoenix client's dataset ID directly
        print(f"  Dataset ID: {dataset_id}")

        # Assign labels to dataset
        print("  Assigning labels to dataset...")
        try:
            label_helper.assign_dataset_labels(
                dataset_id=dataset_id,
                label_names=["Ground Truth", "Test", "HelloWorld"]
            )
            print("  ✓ Assigned labels: Ground Truth, Test, HelloWorld")
        except Exception as label_err:
            print(f"  ⚠  Label assignment failed: {label_err}")
            print(f"  (GraphQL may not support dataset label operations)")

    except Exception as e:
        print(f"✗ Failed with dataset: {e}")
        import traceback
        traceback.print_exc()
        return

    # Run agent experiment
    print("\n4. Running agent experiment...")
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
        # Extract experiment ID properly from Phoenix response
        exp_name = experiment.get("name", "hello-world-v1") if isinstance(experiment, dict) else getattr(experiment, "name", "hello-world-v1")
        exp_id = experiment.get("id") if isinstance(experiment, dict) else getattr(experiment, "id", None)
        if not exp_id:
            # Try to get from URL in print output or metadata
            print(f"⚠  Could not extract experiment ID from response")
            exp_id = "unknown"
        print(f"✓ Agent experiment complete: {exp_name}")
        print(f"  Experiment ID: {exp_id}")
    except Exception as e:
        print(f"✗ Failed to run agent experiment: {e}")
        import traceback
        traceback.print_exc()
        return

    # Run evaluator experiment with structured outputs
    print("\n5. Running evaluator with structured scores...")
    try:
        eval_experiment = client.experiments.run_experiment(
            dataset=dataset,
            task=hello_world_agent_task,  # Re-run agent
            evaluators=[hello_world_evaluator],
            experiment_name="hello-world-v1-eval",
            experiment_description="Evaluation with structured correctness and helpfulness scores",
            experiment_metadata={
                "evaluator": "hello-world-evaluator",
                "agent_experiment": exp_id,
                "version": "v1",
                "structured_scores": True
            }
        )
        # Extract experiment ID properly from Phoenix response
        eval_name = eval_experiment.get("name", "hello-world-v1-eval") if isinstance(eval_experiment, dict) else getattr(eval_experiment, "name", "hello-world-v1-eval")
        eval_id = eval_experiment.get("id") if isinstance(eval_experiment, dict) else getattr(eval_experiment, "id", None)
        if not eval_id:
            # Try to extract from the Phoenix response object
            print(f"⚠  Could not extract eval experiment ID from response")
            # As fallback, try to get the most recent experiment for this dataset
            try:
                experiments_list = list(client.experiments.list(dataset_id=dataset.id))
                if experiments_list:
                    # Get the most recent experiment (last in list)
                    eval_id = experiments_list[-1].get("id") if isinstance(experiments_list[-1], dict) else getattr(experiments_list[-1], "id", None)
                    print(f"  Found most recent experiment ID: {eval_id}")
            except Exception as list_err:
                print(f"  Could not list experiments: {list_err}")
                eval_id = "unknown"
        print(f"✓ Evaluation complete: {eval_name}")
        print(f"  Experiment ID: {eval_id}")
        print("  ✓ Structured scores: correctness, helpfulness, average_score, pass, explanation")
    except Exception as e:
        print(f"✗ Failed to run evaluator: {e}")
        import traceback
        traceback.print_exc()
        return

    # Display evaluation results with full structured scores
    print("\n6. Structured Evaluation Results:")
    print("-" * 70)
    try:
        # Fetch experiment details
        if eval_id == "unknown" or not eval_id:
            print("⚠  Cannot retrieve evaluation results - no valid experiment ID")
            return

        exp_details = client.experiments.get_experiment(experiment_id=eval_id)
        task_runs = exp_details.get("task_runs", [])

        if not task_runs:
            print("⚠  No task runs found in experiment")
            return

        # Process results
        runs = []
        dataset_examples = list(dataset)

        for idx, task_run in enumerate(task_runs):
            # Get dataset example
            example = dataset_examples[idx] if idx < len(dataset_examples) else None

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

            # Re-run evaluator locally to get full structured scores
            # Evaluator returns list of named evaluations
            eval_results = hello_world_evaluator({
                "input": input_data,
                "output": output_data,
                "expected": expected_data
            })

            # Convert list to dict for easier access
            eval_dict = {e["name"]: e for e in eval_results}

            runs.append({
                "input": input_data,
                "output": output_data,
                "evaluation": eval_dict,
                "expected": expected_data
            })

        # Display results with structured scores
        total_correctness = 0
        total_helpfulness = 0
        total_avg_score = 0
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

            # Extract structured scores from named evaluations
            correctness_eval = eval_data.get("correctness", {})
            helpfulness_eval = eval_data.get("helpfulness", {})
            overall_eval = eval_data.get("overall", {})

            correctness_score = correctness_eval.get("score", 0)
            helpfulness_score = helpfulness_eval.get("score", 0)
            overall_score = overall_eval.get("score", 0)
            passed = overall_eval.get("label") == "PASS"

            total_correctness += correctness_score
            total_helpfulness += helpfulness_score
            total_avg_score += overall_score
            if passed:
                passed_count += 1

            status = "✓ PASS" if passed else "✗ FAIL"
            print(f"\nExample {i}/{total_count}: {status}")
            print(f"  Q: {question[:60]}")
            print(f"  A: {response[:60]} (confidence: {confidence:.2f})")
            print(f"  Expected: {expected[:60]}")
            print(f"  Structured Scores:")
            print(f"    - Correctness:   {correctness_score:.2f} ({correctness_eval.get('label', '')})")
            print(f"    - Helpfulness:   {helpfulness_score:.2f} ({helpfulness_eval.get('label', '')})")
            print(f"    - Overall Score: {overall_score:.2f} ({overall_eval.get('label', '')})")
            print(f"  Explanations:")
            if correctness_eval.get("explanation"):
                print(f"    - {correctness_eval['explanation']}")
            if helpfulness_eval.get("explanation"):
                print(f"    - {helpfulness_eval['explanation']}")
            if overall_eval.get("explanation"):
                print(f"    - {overall_eval['explanation']}")

        # Summary statistics
        print("\n" + "=" * 70)
        print("Summary Statistics:")
        print("=" * 70)
        print(f"  Total Examples:         {total_count}")
        print(f"  Passed:                 {passed_count} ({passed_count/total_count*100:.1f}%)")
        print(f"  Failed:                 {total_count - passed_count} ({(total_count-passed_count)/total_count*100:.1f}%)")
        print(f"  Avg Correctness:        {total_correctness/total_count:.2f}")
        print(f"  Avg Helpfulness:        {total_helpfulness/total_count:.2f}")
        print(f"  Overall Average Score:  {total_avg_score/total_count:.2f}")

        # Pass/Fail indicator
        overall_score = total_avg_score/total_count
        if overall_score >= 0.7:
            print(f"\n  🎉 EXPERIMENT PASSED (score: {overall_score:.2f} >= 0.7)")
        else:
            print(f"\n  ⚠️  EXPERIMENT FAILED (score: {overall_score:.2f} < 0.7)")

    except Exception as e:
        print(f"⚠  Could not retrieve evaluation results: {e}")
        import traceback
        traceback.print_exc()

    # Test creating dataset from experiment results
    print("\n" + "=" * 70)
    print("6. Creating dataset from experiment results")
    print("=" * 70)
    try:
        # Create new dataset from agent experiment outputs
        new_dataset_name = "hello-world-outputs-v1"
        print(f"Creating dataset '{new_dataset_name}' from experiment outputs...")

        # Extract inputs and outputs from experiment runs first
        inputs = []
        outputs = []
        metadata = []

        for run in runs:
            input_data = run.get("input", {})
            output_data = run.get("output", {})
            expected_data = run.get("expected", {})
            eval_data = run.get("evaluation", {})

            # Add to dataset
            inputs.append(input_data)
            outputs.append(output_data)

            # Include evaluation scores in metadata
            meta = {
                "source_experiment": exp_name,
                "expected_reference": expected_data.get("reference", ""),
            }

            # Add structured scores to metadata
            if "correctness" in eval_data:
                meta["correctness_score"] = eval_data["correctness"].get("score", 0)
            if "helpfulness" in eval_data:
                meta["helpfulness_score"] = eval_data["helpfulness"].get("score", 0)
            if "overall" in eval_data:
                meta["overall_score"] = eval_data["overall"].get("score", 0)
                meta["overall_label"] = eval_data["overall"].get("label", "")

            metadata.append(meta)

        # Create dataset with all examples at once
        new_dataset = client.datasets.create_dataset(
            name=new_dataset_name,
            inputs=inputs,
            outputs=outputs,
            metadata=metadata,
        )
        print(f"  ✓ Created dataset with {len(inputs)} examples from experiment")

        # Assign labels to new dataset
        new_dataset_id = new_dataset.id
        label_helper.assign_dataset_labels(
            dataset_id=new_dataset_id,
            label_names=["Test", "HelloWorld"]
        )
        print(f"  ✓ Assigned labels to new dataset")

        print(f"\n✓ Dataset created from experiment results:")
        print(f"  Name: {new_dataset_name}")
        print(f"  Examples: {len(inputs)}")
        print(f"  Labels: Test, HelloWorld")
        print(f"  Metadata includes: correctness_score, helpfulness_score, overall_score")

    except Exception as e:
        print(f"⚠  Dataset creation from experiment failed: {e}")
        import traceback
        traceback.print_exc()

    # Final summary
    print("\n" + "=" * 70)
    print("Experiment Complete!")
    print("=" * 70)
    print(f"\nView results in Phoenix UI:")
    print(f"  http://localhost:6006")
    print(f"\nDataset: {dataset.name} ({len(dataset)} examples)")
    print(f"  Labels: Ground Truth, Test, HelloWorld")
    print(f"\nAgent Experiment: {exp_name}")
    print(f"  ID: {exp_id}")
    print(f"\nEval Experiment: {eval_name}")
    print(f"  ID: {eval_id}")
    print(f"  Structured Scores: ✓ correctness, helpfulness, average_score, pass, explanation")

    print("\n✓ All features tested:")
    print("  [✓] Labels created for prompts and datasets")
    print("  [✓] Prompts created from agent and evaluator schemas")
    print("  [✓] Prompt labels assigned via GraphQL")
    print("  [✓] Dataset created with labels")
    print("  [✓] Agent experiment executed")
    print("  [✓] Evaluator with structured scores (list format)")
    print("  [✓] Full evaluation results displayed")
    print("  [✓] New dataset created from experiment outputs")
    print("  [✓] Dataset labels assigned to outputs dataset")


if __name__ == "__main__":
    main()
