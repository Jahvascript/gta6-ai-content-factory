"""Register source rights. Does not authorize publishing."""

import argparse
import sqlite3
from datetime import datetime, timezone
from publishing_eligibility import DB

PLATFORMS = ("youtube", "instagram", "tiktok")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-id", required=True)
    parser.add_argument(
        "--type",
        required=True,
        choices=("original", "licensed", "permission")
    )
    parser.add_argument("--creator", required=True)
    parser.add_argument("--reference", required=True)
    parser.add_argument("--scope", required=True)
    parser.add_argument(
        "--platforms",
        nargs="+",
        required=True,
        choices=PLATFORMS
    )
    parser.add_argument("--expires")
    parser.add_argument("--commercial", action="store_true")
    parser.add_argument("--confirm", action="store_true")
    args = parser.parse_args()

    if args.expires:
        expiry = datetime.fromisoformat(
            args.expires.replace("Z", "+00:00")
        )
        if expiry.tzinfo is None:
            parser.error("--expires requires timezone information")
        if expiry <= datetime.now(timezone.utc):
            parser.error("Permission has already expired")

    print("=== SOURCE RIGHTS REGISTRATION ===")
    print("Source:", args.source_id)
    print("Type:", args.type)
    print("Creator:", args.creator)
    print("Platforms:", ", ".join(args.platforms))
    print("Scope:", args.scope)
    print("Reference:", args.reference)
    print("Commercial use:", args.commercial)
    print("Expiration:", args.expires or "Not specified")

    if not args.confirm:
        print("PREVIEW ONLY. Add --confirm to register.")
        return

    now = datetime.now(timezone.utc).isoformat()
    conn = sqlite3.connect(DB)

    try:
        conn.execute("BEGIN IMMEDIATE")

        exists = conn.execute("""
            SELECT 1 FROM publishing_queue
            WHERE source_id = ?
            LIMIT 1
        """, (args.source_id,)).fetchone()

        if not exists:
            raise ValueError("Unknown source ID")

        registered = conn.execute("""
            SELECT 1 FROM source_rights
            WHERE source_id = ?
        """, (args.source_id,)).fetchone()

        if registered:
            raise ValueError(
                "Source already registered. "
                "Existing rights cannot be overwritten."
            )

        conn.execute("""
            INSERT INTO source_rights (
                source_id, ownership_type, creator_name,
                permission_reference, permission_scope,
                commercial_use_allowed,
                modifications_allowed,
                valid_until, verified_at
            )
            VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)
        """, (
            args.source_id,
            args.type,
            args.creator,
            args.reference,
            args.scope,
            int(args.commercial),
            args.expires,
            now
        ))

        for platform in args.platforms:
            conn.execute("""
                INSERT INTO source_rights_platforms (
                    source_id, platform, allowed
                )
                VALUES (?, ?, 1)
            """, (args.source_id, platform))

        conn.execute("""
            INSERT INTO publishing_authorization_events (
                source_id, platform, event_type,
                event_details
            )
            VALUES (?, ?, 'rights_registered', ?)
        """, (
            args.source_id,
            "youtube" if "youtube" in args.platforms
            else args.platforms[0],
            f"Ownership: {args.type}; reference: {args.reference}"
        ))

        conn.commit()

    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    print("PASS: Source rights registered.")
    print("Publishing authorization remains disabled.")
    print("Nothing scheduled, uploaded, or published.")


if __name__ == "__main__":
    main()
