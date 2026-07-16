import asyncio

from app.services.ai_singleflight import ChatSingleFlight


def test_same_key_waits_for_the_first_flight():
    async def scenario():
        flights = ChatSingleFlight()
        first = await flights.acquire("same-isolated-key")
        second_task = asyncio.create_task(flights.acquire("same-isolated-key"))
        await asyncio.sleep(0)
        assert not second_task.done()
        await first.release()
        second = await second_task
        try:
            assert second.waited is True
        finally:
            await second.release()

    asyncio.run(scenario())


def test_different_keys_never_share_a_flight():
    async def scenario():
        flights = ChatSingleFlight()
        first = await flights.acquire("user-a-scope-a")
        second = await flights.acquire("user-b-scope-b")
        try:
            assert second.waited is False
        finally:
            await second.release()
            await first.release()

    asyncio.run(scenario())
