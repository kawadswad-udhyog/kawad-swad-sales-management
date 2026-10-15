from app.security import hash_password, verify_password

def test_password_hash_and_verify():
    hashed=hash_password("Example-Password-123!")
    assert hashed != "Example-Password-123!"
    assert verify_password("Example-Password-123!",hashed)
    assert not verify_password("wrong-password",hashed)
