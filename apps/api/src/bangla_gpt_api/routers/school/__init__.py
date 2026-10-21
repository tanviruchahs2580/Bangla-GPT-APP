"""School / tenancy routes -- one package, four cohesive surfaces.

This domain used to be a single 1060-line module (the audit's "god module"
list, C-03 / AUD-CD-02). It is split by responsibility, not by size:

``_admin``       platform-admin tenancy: schools, invites, content versions,
                 the government aggregate export;
``_onboarding``  staff invites and their redemption, the own-school overview,
                 classroom registration;
``_health``      the whole-school learning-health dashboard;
``_roster``      the student/teacher/classroom rosters;
``_analytics``   coverage and trend analytics (k-anonymity-safe aggregates);
``_shared``      the tenancy scope resolution and room/roster lookups.

Behaviour is unchanged: same paths, same order (which is why the sub-routers
are included in this sequence -- it is the order `docs/route_baseline.md`
records), same validation and status codes, same auth guards. Only
``_health``, ``_roster.school_students`` and ``_analytics.school_coverage``
were additionally decomposed, which is what brought their cyclomatic
complexity below the ratchet threshold (see the C-05 review in
``docs/architecture.md``).
"""

from fastapi import APIRouter

from . import _admin, _analytics, _health, _onboarding, _roster

#: Inclusion order mirrors the pre-split file so the served route table (and
#: therefore `docs/route_baseline.md` and the OpenAPI document) is identical.
router = APIRouter()
for _sub in (_admin, _onboarding, _health, _roster, _analytics):
    router.include_router(_sub.router)

__all__ = ["router"]
