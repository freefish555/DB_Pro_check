"""Public model metadata and immutable profile identity for queued work."""


def public_profile(profile):
    return {'id': profile.id, 'service_id': profile.service_id, 'model': profile.model,
            'enabled': profile.enabled, 'version': profile.version,
            'has_key': bool(profile.key_encrypted), 'created_at': profile.created_at}


def profile_snapshot(profile, service):
    return {'profile_id': profile.id, 'owner_id': profile.owner_id,
            'profile_version': profile.version, 'service_id': service.id,
            'service_version': service.version, 'base_url': service.base_url,
            'model': profile.model}


def profile_is_current(snapshot, profile, service):
    return bool(profile and service and profile.enabled and service.enabled and
                snapshot.get('profile_id') == profile.id and
                snapshot.get('owner_id') == profile.owner_id and
                snapshot.get('profile_version') == profile.version and
                snapshot.get('service_id') == service.id and
                snapshot.get('service_version') == service.version and
                snapshot.get('base_url') == service.base_url and
                snapshot.get('model') == profile.model)
