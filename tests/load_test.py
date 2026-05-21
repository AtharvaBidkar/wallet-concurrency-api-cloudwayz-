import asyncio
import time
import sys
from decimal import Decimal
import httpx

BASE_URL = "http://localhost:8000"

async def test_concurrency():
    print("Starting Concurrency Load Test...")
    print(f"Target API: {BASE_URL}")

    # Set up client with custom limits to prevent client-side queueing
    limits = httpx.Limits(max_connections=600, max_keepalive_connections=600)
    # Set a generous timeout to handle high load without timing out
    timeout = httpx.Timeout(60.0, connect=10.0)

    async with httpx.AsyncClient(limits=limits, timeout=timeout) as client:
        # Step 1: Create a wallet with balance 0.0
        print("Creating a new wallet with initial balance 0.00...")
        try:
            create_resp = await client.post(f"{BASE_URL}/wallets", json={"balance": 0.00})
            create_resp.raise_for_status()
        except Exception as e:
            print(f"Failed to create wallet: {e}")
            if hasattr(e, 'response') and e.response:
                print(f"Response: {e.response.text}")
            sys.exit(1)

        wallet_data = create_resp.json()
        wallet_id = wallet_data["id"]
        print(f"Created wallet ID: {wallet_id} with balance: {wallet_data['balance']} (version: {wallet_data['version']})")

        # Step 2: Fire 500 concurrent credits of 1.0 each
        n_requests = 500
        delta = 1.00
        print(f"Firing {n_requests} concurrent PATCH requests of +{delta}...")

        start_time = time.perf_counter()

        async def send_credit():
            try:
                resp = await client.patch(
                    f"{BASE_URL}/wallets/{wallet_id}/credit",
                    json={"delta": delta}
                )
                return resp.status_code, resp.json()
            except Exception as exc:
                return 0, str(exc)

        # Gather all requests to run concurrently
        tasks = [send_credit() for _ in range(n_requests)]
        results = await asyncio.gather(*tasks)

        end_time = time.perf_counter()
        elapsed = end_time - start_time

        # Analyze results
        success_count = 0
        error_count = 0
        status_codes = {}

        for status_code, details in results:
            status_codes[status_code] = status_codes.get(status_code, 0) + 1
            if status_code == 200:
                success_count += 1
            else:
                error_count += 1

        print(f"\n--- Load Test Results ---")
        print(f"Completed {n_requests} requests in {elapsed:.4f} seconds.")
        print(f"Successes: {success_count}")
        print(f"Failures/Errors: {error_count}")
        print(f"Status codes distribution: {status_codes}")

        # Step 3: Fetch final balance and assert
        print("\nFetching final balance...")
        try:
            get_resp = await client.get(f"{BASE_URL}/wallets/{wallet_id}")
            get_resp.raise_for_status()
        except Exception as e:
            print(f"Failed to retrieve final wallet balance: {e}")
            sys.exit(1)

        final_wallet = get_resp.json()
        final_balance = Decimal(str(final_wallet["balance"]))
        expected_balance = Decimal(str(n_requests * delta))
        expected_version = wallet_data["version"] + n_requests

        print(f"Final Wallet Balance: {final_balance} (Expected: {expected_balance})")
        print(f"Final Wallet Version: {final_wallet['version']} (Expected: {expected_version})")

        # Assertion
        assert final_balance == expected_balance, f"Assertion failed: final balance is {final_balance}, expected {expected_balance}"
        assert final_wallet["version"] == expected_version, f"Assertion failed: final version is {final_wallet['version']}, expected {expected_version}"
        print("\nCONCURRENCY LOAD TEST PASSED SUCCESSFULLY WITHOUT DATA LOSS OR CORRUPTION!")

if __name__ == "__main__":
    asyncio.run(test_concurrency())
