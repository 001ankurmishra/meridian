import argparse
import os
import sys
import uuid

from sqlalchemy import Engine, create_engine, text

from meridian.identity.tokens import (
    issue_token,
    revoke_all_tokens_for_user,
    revoke_token,
)


def get_engine() -> Engine:
    db_url = os.environ.get("APP_DATABASE_URL")
    if not db_url:
        print(
            "Error: APP_DATABASE_URL environment variable is not set.",
            file=sys.stderr,
        )
        sys.exit(1)
    return create_engine(db_url)


def cmd_issue(args: argparse.Namespace) -> None:
    engine = get_engine()

    # lookup user by email
    with engine.begin() as conn:
        user_row = conn.execute(
            text("SELECT user_id FROM users WHERE email = :email"),
            {"email": args.email}
        ).fetchone()

    if not user_row:
        print(f"Error: User with email {args.email} not found.", file=sys.stderr)
        sys.exit(1)

    user_id = user_row[0]

    try:
        token = issue_token(engine, user_id, ttl_hours=args.ttl, label=args.label)
        print("Token successfully issued.")
        print(f"Token ID: {token.token_id}")
        print(f"User ID:  {token.user_id}")
        print(f"Expires:  {token.expires_at}")
        print(f"Token:    {token.plaintext_token}")
        print("IMPORTANT: The token will not be displayed again. Save it now.")
    except ValueError as e:
        print(f"Error issuing token: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_revoke(args: argparse.Namespace) -> None:
    engine = get_engine()
    try:
        token_id = uuid.UUID(args.token_id)
    except ValueError:
        print("Error: Invalid token_id format.", file=sys.stderr)
        sys.exit(1)

    success = revoke_token(engine, token_id)
    if success:
        print(f"Token {token_id} revoked.")
    else:
        print(f"Token {token_id} not found or already revoked.", file=sys.stderr)
        sys.exit(1)


def cmd_revoke_all(args: argparse.Namespace) -> None:
    engine = get_engine()

    with engine.begin() as conn:
        user_row = conn.execute(
            text("SELECT user_id FROM users WHERE email = :email"),
            {"email": args.email}
        ).fetchone()

    if not user_row:
        print(f"Error: User with email {args.email} not found.", file=sys.stderr)
        sys.exit(1)

    user_id = user_row[0]
    count = revoke_all_tokens_for_user(engine, user_id)
    print(f"Revoked {count} tokens for user {args.email}.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Meridian API Token CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # issue
    parser_issue = subparsers.add_parser("issue", help="Issue a new token")
    parser_issue.add_argument("email", help="Target user's email")
    parser_issue.add_argument(
        "--ttl", type=int, default=168, help="TTL in hours (max 168)"
    )
    parser_issue.add_argument("--label", help="Optional label for the token")
    parser_issue.set_defaults(func=cmd_issue)

    # revoke
    parser_revoke = subparsers.add_parser("revoke", help="Revoke a single token")
    parser_revoke.add_argument("token_id", help="The ID of the token to revoke")
    parser_revoke.set_defaults(func=cmd_revoke)

    # revoke-all
    parser_revoke_all = subparsers.add_parser(
        "revoke-all", help="Revoke all tokens for a user"
    )
    parser_revoke_all.add_argument("email", help="Target user's email")
    parser_revoke_all.set_defaults(func=cmd_revoke_all)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
