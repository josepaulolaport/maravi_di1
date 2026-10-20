"""Static import-boundary checker for the `di1` package.

Sources: CLAUDE.md §3, backend/CLAUDE.md, plan §0-§1, interfaces.md "Scope and structural rules"
and "DI composition". Each file is parsed with `ast`; every import (relative ones resolved,
`TYPE_CHECKING` blocks included) is checked. A violation reads
``"<rule>: <file> imports <module>"`` (or ``calls`` / ``is outside`` for the last two rules).

Rules:

- ``cross-module``: code in ``modules/<m>/`` and in ``workers/`` reaches another module only
  through its ``public.py``. ``from di1.modules.<other> import public`` is the only accepted
  form that names the package itself.
- ``module-init``: a module's ``__init__.py`` imports nothing (no re-export path around
  ``public.py``).
- ``domain-purity``: ``domain/`` is deterministic and free of I/O and side effects. It imports
  only the standard library, ``di1.shared`` and its own module's domain; it never imports a
  standard-library module whose purpose is filesystem, network, database, environment,
  process, concurrency, logging or OS-entropy access; and it never calls the system clock,
  random identifiers or I/O builtins (``datetime.now``, ``date.today``, ``time.monotonic``,
  ``uuid.uuid4``, ``open``, ``print``, ...). Randomness is never generated internally: the
  module-level ``random`` functions, ``random.seed``, ``SystemRandom`` and an unseeded
  ``random.Random()`` are forbidden, while an injected generator (``rng: random.Random``) or one
  built from an explicit seed (``random.Random(seed)``) is allowed. Pure utilities stay
  allowed: ``datetime`` arithmetic, ``decimal``, ``enum``, ``dataclasses``, ``uuid.UUID``.
- ``layering``: ``application/`` does not import its module's ``infrastructure/`` or
  ``presentation/``; ``infrastructure/`` does not import ``presentation/``; ``presentation/``
  (HTTP routers, message handlers) does not import ``infrastructure/``, so business logic
  stays in ``application/``; ``public.py`` exposes neither.
- ``fastapi``: FastAPI/Starlette only in ``presentation/``, a module's ``dependencies.py``
  (its dependency providers), ``composition/`` and ``main.py``.
- ``sql``: SQLAlchemy/psycopg/Alembic only in ``infrastructure/``, ``dependencies.py``,
  ``platform/`` and ``composition/``.
- ``pydantic``: Pydantic only in ``presentation/`` and ``platform/`` (settings).
- ``messaging``: aio-pika only in ``platform/`` and ``workers/`` (shared RabbitMQ
  infrastructure). Module code uses only the outbox and envelope parts of
  ``di1.platform.messaging``; a module's ``presentation/messaging/`` (its consumers and
  handlers) may also use ``di1.platform.messaging.consumer``.
- ``shared-independent``: ``platform/`` and ``shared/`` import no module.
- ``entry-point``: ``di1.main`` and ``di1.composition`` are imported only by ``main.py`` and
  ``composition/``; workers may use only ``di1.composition.consumers``; ``di1.workers`` is
  imported only by ``workers/``, ``composition/`` and ``main.py``.
- ``dynamic-import``: no ``importlib.import_module`` or ``__import__`` calls.
- ``layout``: every file sits in the plan §1 layout. ``infrastructure/`` may hold any outbound
  adapter; ``presentation/`` holds ``http/`` and ``messaging/``.
"""

from __future__ import annotations

import ast
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

ROOT = "di1"
MODULES = f"{ROOT}.modules"

FASTAPI_LIBRARIES = ("fastapi", "starlette")
SQL_LIBRARIES = ("sqlalchemy", "psycopg", "alembic")
BROKER_LIBRARIES = ("aio_pika", "aiormq", "pika")
PYDANTIC_LIBRARIES = ("pydantic", "pydantic_settings", "pydantic_core")
# Standard-library modules whose purpose is a side effect: filesystem, network, database,
# environment and process, concurrency, logging (it belongs in the outer layers: domain code
# reports failures through exceptions and explicit results), OS entropy.
DOMAIN_FORBIDDEN_STDLIB = frozenset(
    {
        "os", "sys", "pathlib", "io", "shutil", "tempfile", "glob", "fileinput", "zipfile",
        "tarfile", "mmap", "socket", "ssl", "select", "selectors", "http", "urllib", "ftplib",
        "smtplib", "poplib", "imaplib", "socketserver", "xmlrpc", "wsgiref", "webbrowser",
        "sqlite3", "dbm", "shelve", "asyncio", "threading", "multiprocessing", "concurrent",
        "subprocess", "signal", "sched", "queue", "logging", "secrets", "getpass",
        "platform", "ctypes",
    }
)  # fmt: skip
# Side-effecting calls inside otherwise pure modules: the system clock, random identifiers and
# I/O builtins. Names are fully qualified after resolving import aliases.
DOMAIN_FORBIDDEN_CALLS = frozenset(
    {
        "datetime.datetime.now", "datetime.datetime.utcnow", "datetime.datetime.today",
        "datetime.date.today", "time.time", "time.time_ns", "time.monotonic",
        "time.monotonic_ns", "time.perf_counter", "time.perf_counter_ns", "time.process_time",
        "time.process_time_ns", "time.thread_time", "time.thread_time_ns", "time.sleep",
        "time.localtime", "time.gmtime", "time.ctime", "time.mktime", "uuid.uuid1",
        "uuid.uuid4", "builtins.open", "builtins.input", "builtins.print",
        "builtins.breakpoint", "builtins.exec", "builtins.eval",
        # internal randomness: the hidden global generator and OS entropy
        "random.random", "random.uniform", "random.triangular", "random.randint",
        "random.randrange", "random.randbytes", "random.getrandbits", "random.choice",
        "random.choices", "random.shuffle", "random.sample", "random.binomialvariate",
        "random.gauss", "random.normalvariate", "random.lognormvariate", "random.expovariate",
        "random.vonmisesvariate", "random.gammavariate", "random.betavariate",
        "random.paretovariate", "random.weibullvariate", "random.seed", "random.setstate",
        "random.SystemRandom",
    }
)  # fmt: skip
# A generator built without an explicit seed is seeded from OS entropy.
SEEDED_GENERATORS = frozenset({"random.Random"})
BUSINESS_MESSAGING = (
    f"{ROOT}.platform.messaging.outbox",
    f"{ROOT}.platform.messaging.envelope",
)
CONSUMER_MESSAGING = (*BUSINESS_MESSAGING, f"{ROOT}.platform.messaging.consumer")

TOP_FILES = frozenset({"__init__.py", "main.py"})
TOP_PACKAGES = frozenset({"modules", "platform", "shared", "composition", "workers"})
MODULE_ENTRIES = frozenset(
    {"__init__.py", "public.py", "dependencies.py", "domain", "application", "infrastructure",
     "presentation"}
)  # fmt: skip
# Allowed entries directly under a layer; a layer missing here (domain, infrastructure) may hold
# any sub-package: infrastructure/ holds every outbound adapter a module needs.
LAYER_ENTRIES = {
    "application": frozenset({"__init__.py", "ports.py", "services", "interfaces"}),
    "presentation": frozenset({"__init__.py", "http", "messaging"}),
}


@dataclass(frozen=True, slots=True)
class SourceFile:
    """A file of the package, located by its path parts relative to the package root."""

    relative: str
    parts: tuple[str, ...]

    @property
    def top(self) -> str:
        return self.parts[0]

    @property
    def module(self) -> str | None:
        """The business module the file belongs to, or None outside ``modules/<m>/``."""
        return self.parts[1] if self.top == "modules" and len(self.parts) >= 3 else None

    @property
    def layer(self) -> str | None:
        """``domain``, ``application``, ``infrastructure``, ``presentation``, or the stem of a
        file directly in the module (``public``, ``dependencies``, ``__init__``)."""
        return self.parts[2].removesuffix(".py") if self.module is not None else None

    @property
    def is_message_consumer(self) -> bool:
        """A module's ``presentation/messaging/`` (its RabbitMQ consumers and handlers)."""
        return (
            self.layer == "presentation" and len(self.parts) >= 5 and self.parts[3] == "messaging"
        )

    def package_parts(self) -> list[str]:
        return [ROOT, *self.parts[:-1]]

    def in_layout(self) -> bool:
        parts = self.parts
        if len(parts) == 1:
            return parts[0] in TOP_FILES
        if parts[0] not in TOP_PACKAGES:
            return False
        if parts[0] != "modules":
            return True
        if len(parts) == 2:
            return parts[1] == "__init__.py"
        if parts[2] not in MODULE_ENTRIES:
            return False
        allowed = LAYER_ENTRIES.get(parts[2])
        return allowed is None or len(parts) == 3 or parts[3] in allowed


@dataclass(frozen=True, slots=True)
class Imported:
    """One imported name. ``via_from`` marks the package of a ``from pkg import x`` statement:
    it is named only as the container of ``x``, which is checked on its own."""

    name: str
    via_from: bool


def _under(name: str, prefixes: tuple[str, ...]) -> bool:
    return any(name == prefix or name.startswith(prefix + ".") for prefix in prefixes)


def _imports(tree: ast.AST, source: SourceFile) -> Iterator[Imported]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield Imported(alias.name, via_from=False)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = source.package_parts()
                base = base[: len(base) - (node.level - 1)]
                module = ".".join([*base, *([node.module] if node.module else [])])
            else:
                module = node.module or ""
            yield Imported(module, via_from=True)
            for alias in node.names:
                if alias.name != "*":
                    yield Imported(f"{module}.{alias.name}", via_from=False)


def _aliases(tree: ast.AST) -> dict[str, str]:
    """Local name → fully qualified name, for every name the file binds by importing."""
    bound: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    bound[alias.asname] = alias.name
                else:
                    first = alias.name.split(".")[0]
                    bound[first] = first
        elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
            for alias in node.names:
                bound[alias.asname or alias.name] = f"{node.module}.{alias.name}"
    return bound


def _called_names(tree: ast.AST) -> Iterator[str]:
    """The fully qualified name of every call whose target is a (dotted) name. A seeded
    generator called without any argument is reported with an ``()`` suffix."""
    bound = _aliases(tree)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        chain: list[str] = []
        target: ast.expr = node.func
        while isinstance(target, ast.Attribute):
            chain.insert(0, target.attr)
            target = target.value
        if not isinstance(target, ast.Name):
            continue
        head = bound.get(target.id, f"builtins.{target.id}" if not chain else target.id)
        name = ".".join([head, *chain])
        unseeded = name in SEEDED_GENERATORS and not node.args and not node.keywords
        yield f"{name}()" if unseeded else name


def _dynamic_imports(tree: ast.AST) -> Iterator[str]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in ("__import__", "import_module"):
                yield func.id
            elif isinstance(func, ast.Attribute) and func.attr == "import_module":
                yield "import_module"


def _cross_module(source: SourceFile, imported: Imported) -> bool:
    if source.module is None and source.top != "workers":
        return False
    name = imported.name
    if not _under(name, (MODULES,)):
        return False
    parts = name.split(".")
    if len(parts) == 2:
        return not imported.via_from
    other = parts[2]
    if other == source.module:
        return False
    package = f"{MODULES}.{other}"
    if name == package:
        return not imported.via_from
    return not _under(name, (f"{package}.public",))


def _rules(source: SourceFile, imported: Imported) -> Iterator[str]:
    name, module, layer, top = imported.name, source.module, source.layer, source.top
    own = f"{MODULES}.{module}" if module else None

    if _cross_module(source, imported):
        yield "cross-module"

    if layer == "__init__" and len(source.parts) == 3 and not _under(name, ("__future__",)):
        yield "module-init"

    if layer == "domain":
        top_level = name.split(".")[0]
        stdlib = top_level in sys.stdlib_module_names and top_level not in DOMAIN_FORBIDDEN_STDLIB
        if not (stdlib or _under(name, (f"{ROOT}.shared", f"{own}.domain"))):
            yield "domain-purity"

    if own is not None:
        inner = {
            "application": (f"{own}.infrastructure", f"{own}.presentation"),
            "infrastructure": (f"{own}.presentation",),
            "presentation": (f"{own}.infrastructure",),
            "public": (f"{own}.infrastructure", f"{own}.presentation"),
        }.get(layer or "", ())
        if inner and _under(name, inner):
            yield "layering"

    if _under(name, FASTAPI_LIBRARIES) and not (
        layer in ("presentation", "dependencies") or top in ("composition", "main.py")
    ):
        yield "fastapi"

    if _under(name, SQL_LIBRARIES) and not (
        layer in ("infrastructure", "dependencies") or top in ("platform", "composition")
    ):
        yield "sql"

    if _under(name, PYDANTIC_LIBRARIES) and not (layer == "presentation" or top == "platform"):
        yield "pydantic"

    if _under(name, BROKER_LIBRARIES) and top not in ("platform", "workers"):
        yield "messaging"
    messaging_package = f"{ROOT}.platform.messaging"
    if (
        top == "modules"
        and _under(name, (messaging_package,))
        and not (name == messaging_package and imported.via_from)
        and not _under(
            name, CONSUMER_MESSAGING if source.is_message_consumer else BUSINESS_MESSAGING
        )
    ):
        yield "messaging"

    if top in ("platform", "shared") and _under(name, (MODULES,)):
        yield "shared-independent"

    if _under(name, (f"{ROOT}.composition", f"{ROOT}.main")) and top not in (
        "composition",
        "main.py",
    ):
        worker_allowed = top == "workers" and (
            (name == f"{ROOT}.composition" and imported.via_from)
            or _under(name, (f"{ROOT}.composition.consumers",))
        )
        if not worker_allowed:
            yield "entry-point"
    if _under(name, (f"{ROOT}.workers",)) and top not in ("workers", "composition", "main.py"):
        yield "entry-point"


def _keep_shortest(found: set[tuple[str, str]]) -> set[tuple[str, str]]:
    """``from pkg import x`` yields both ``pkg`` and ``pkg.x``; report each rule once, on the
    shortest name."""
    return {
        (rule, name)
        for rule, name in found
        if not any(rule == r and name.startswith(n + ".") for r, n in found)
    }


def find_violations(package: Path) -> list[str]:
    """All boundary violations under ``package`` (the ``di1`` directory), sorted."""
    report: set[str] = set()
    for path in sorted(package.rglob("*.py")):
        relative = path.relative_to(package)
        source = SourceFile(relative=relative.as_posix(), parts=relative.parts)
        if not source.in_layout():
            report.add(f"layout: {source.relative} is outside the plan §1 layout")
        tree = ast.parse(path.read_text(), filename=str(path))
        found = {(rule, i.name) for i in _imports(tree, source) for rule in _rules(source, i)}
        for rule, name in _keep_shortest(found):
            report.add(f"{rule}: {source.relative} imports {name}")
        for call in set(_dynamic_imports(tree)):
            report.add(f"dynamic-import: {source.relative} calls {call}")
        if source.layer == "domain":
            unseeded = {f"{name}()" for name in SEEDED_GENERATORS}
            for call in set(_called_names(tree)) & (DOMAIN_FORBIDDEN_CALLS | unseeded):
                report.add(f"domain-purity: {source.relative} calls {call}")
    return sorted(report)
