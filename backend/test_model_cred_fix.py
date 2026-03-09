import asyncio
import os

# Mocking app-specific imports for the test script
import sys
import uuid

from sqlalchemy import delete

# Assuming the script is run from the backend directory
sys.path.append(os.getcwd())

from app.core.database import SessionLocal
from app.models.model_credential import ModelCredential
from app.repositories.model_credential import ModelCredentialRepository


async def test_credential_lookup():
    async with SessionLocal() as db:
        repo = ModelCredentialRepository(db)

        # 1. Setup a test user and a credential
        test_user_id = str(uuid.uuid4())
        provider_name = "test-provider-" + str(uuid.uuid4())[:8]

        print(f"Testing with user_id: {test_user_id} and provider: {provider_name}")

        # Create a user-specific credential
        cred = ModelCredential(
            user_id=test_user_id, provider_name=provider_name, credentials="encrypted_stuff", is_valid=True
        )
        db.add(cred)
        await db.commit()

        try:
            # 2. Test lookup with correct user_id
            found = await repo.get_by_provider_name(provider_name, user_id=test_user_id)
            assert found is not None, "Should find credential for the specific user"
            print("✓ Found credential with correct user_id")

            # 3. Test lookup with different user_id
            other_user_id = str(uuid.uuid4())
            not_found = await repo.get_by_provider_name(provider_name, user_id=other_user_id)
            assert not_found is None, "Should NOT find credential for a different user"
            print("✓ Correctly did not find credential for other user_id")

            # 4. Test lookup with None user_id (global)
            global_not_found = await repo.get_by_provider_name(provider_name, user_id=None)
            assert global_not_found is None, "Should NOT find user-specific credential when searching for global"
            print("✓ Correctly did not find user-specific credential in global search")

            # 5. Setup a global credential
            global_provider = "global-provider-" + str(uuid.uuid4())[:8]
            global_cred = ModelCredential(
                user_id=None, provider_name=global_provider, credentials="global_encrypted_stuff", is_valid=True
            )
            db.add(global_cred)
            await db.commit()

            # 6. Test global lookup
            found_global = await repo.get_by_provider_name(global_provider, user_id=None)
            assert found_global is not None, "Should find global credential"
            print("✓ Found global credential")

        finally:
            # Cleanup
            await db.execute(
                delete(ModelCredential).where(ModelCredential.provider_name.in_([provider_name, global_provider]))
            )
            await db.commit()


if __name__ == "__main__":
    asyncio.run(test_credential_lookup())
