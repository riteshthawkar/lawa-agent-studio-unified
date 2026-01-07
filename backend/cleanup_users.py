from django.contrib.auth import get_user_model
User = get_user_model()
email = "demo@webbotify.com"
password = "password123"

try:
    # Ensure demo user exists
    if not User.objects.filter(email=email).exists():
        print(f"Creating user {email}...")
        User.objects.create_user(username=email, email=email, password=password)
    else:
        print(f"User {email} exists. Resetting password...")
        u = User.objects.get(email=email)
        u.set_password(password)
        u.save()

    # Delete others
    deleted_count, _ = User.objects.exclude(email=email).delete()
    print(f"Deleted {deleted_count} other users.")
    print("DONE")
except Exception as e:
    print(f"Error: {e}")
