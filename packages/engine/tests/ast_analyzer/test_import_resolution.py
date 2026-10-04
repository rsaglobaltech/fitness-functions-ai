"""Import resolution: relative imports, ambiguity, stdlib shadowing, file walking."""

from __future__ import annotations

from pathlib import Path

import pytest
from arch_guardian_engine.ast_analyzer import analyze_repo


def _write(root: Path, rel: str, content: str = "") -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def _edges(root: Path) -> set[tuple[str, str]]:
    return set(analyze_repo(root).import_graph.edges())


# --- Python ----------------------------------------------------------------


@pytest.mark.unit
def test_python_relative_imports_resolve_against_importer(tmp_path: Path) -> None:
    _write(tmp_path, "app/__init__.py")
    _write(tmp_path, "app/orders/__init__.py", "from . import service\n")
    _write(tmp_path, "app/orders/service.py", "from .repo import Repo\nfrom ..billing import tax\n")
    _write(tmp_path, "app/orders/repo.py", "class Repo: ...\n")
    _write(tmp_path, "app/billing/__init__.py")
    _write(tmp_path, "app/billing/tax.py")
    # Same basename elsewhere must not attract the relative import.
    _write(tmp_path, "app/users/repo.py")

    assert _edges(tmp_path) == {
        ("app.orders", "app.orders.service"),
        ("app.orders.service", "app.orders.repo"),
        ("app.orders.service", "app.billing.tax"),
    }


@pytest.mark.unit
def test_python_from_package_import_submodule(tmp_path: Path) -> None:
    _write(tmp_path, "src/shop/__init__.py")
    _write(tmp_path, "src/shop/cart.py", "from shop import pricing\nfrom shop.pricing import X\n")
    _write(tmp_path, "src/shop/pricing.py")
    assert _edges(tmp_path) == {("src.shop.cart", "src.shop.pricing")}


@pytest.mark.unit
def test_python_stdlib_import_does_not_hit_local_module_inside_package(tmp_path: Path) -> None:
    _write(tmp_path, "pkg/__init__.py")
    _write(tmp_path, "pkg/logging.py")
    _write(tmp_path, "pkg/service.py", "import logging\nimport json\n")
    _write(tmp_path, "pkg/util/__init__.py")
    _write(tmp_path, "pkg/util/json.py")
    assert _edges(tmp_path) == set()


@pytest.mark.unit
def test_ambiguous_suffix_without_tiebreak_creates_no_edge(tmp_path: Path) -> None:
    # Two source roots each exposing `common`: the importer shares no prefix
    # with either, so guessing would risk a false cycle.
    _write(tmp_path, "a/common.py")
    _write(tmp_path, "b/common.py")
    _write(tmp_path, "main.py", "import common\n")
    assert _edges(tmp_path) == set()


# --- TypeScript / JavaScript ---------------------------------------------


@pytest.mark.unit
def test_ts_relative_imports_do_not_create_false_cycles(tmp_path: Path) -> None:
    # Two unrelated `Order` files; each module imports its own sibling.
    _write(tmp_path, "src/billing/Order.ts", "export class Order {}\n")
    _write(tmp_path, "src/billing/Invoice.ts", 'import { Order } from "./Order";\n')
    _write(tmp_path, "src/shipping/Order.ts", 'import { Invoice } from "../billing/Invoice";\n')
    assert _edges(tmp_path) == {
        ("src.billing.Invoice", "src.billing.Order"),
        ("src.shipping.Order", "src.billing.Invoice"),
    }


@pytest.mark.unit
def test_ts_index_reexport_require_and_dynamic_import(tmp_path: Path) -> None:
    _write(tmp_path, "src/domain/index.ts", 'export * from "./order";\n')
    _write(tmp_path, "src/domain/order.ts")
    _write(tmp_path, "src/infra/db.js", 'const cfg = require("../config.js");\n')
    _write(tmp_path, "src/config.js")
    _write(tmp_path, "src/app.ts", 'import "./domain";\nconst m = await import("./infra/db");\n')
    assert _edges(tmp_path) == {
        ("src.domain.index", "src.domain.order"),
        ("src.infra.db", "src.config"),
        ("src.app", "src.domain.index"),
        ("src.app", "src.infra.db"),
    }


@pytest.mark.unit
def test_ts_packages_are_external_and_aliases_resolve(tmp_path: Path) -> None:
    _write(tmp_path, "src/shared/api.ts")
    _write(
        tmp_path,
        "src/pages/Home.tsx",
        'import React from "react";\n'
        'import { Module } from "@nestjs/common";\n'
        'import { api } from "@/shared/api";\n',
    )
    assert _edges(tmp_path) == {("src.pages.Home", "src.shared.api")}


@pytest.mark.unit
def test_ts_relative_import_escaping_repo_is_ignored(tmp_path: Path) -> None:
    _write(tmp_path, "a.ts", 'import x from "../../outside";\n')
    assert _edges(tmp_path) == set()


# --- Walking ----------------------------------------------------------------


@pytest.mark.unit
def test_walk_skips_vendor_dirs_minified_large_and_declaration_files(tmp_path: Path) -> None:
    _write(tmp_path, "src/ok.ts")
    _write(tmp_path, "node_modules/lib/index.js")
    _write(tmp_path, "src/vendor.min.js")
    _write(tmp_path, "src/types.d.ts")
    _write(tmp_path, "src/huge.py", "x = 1\n" * 50)
    analysis = analyze_repo(tmp_path, max_file_bytes=100)
    assert set(analysis.modules) == {"src.ok"}


@pytest.mark.unit
def test_deeply_nested_code_does_not_hit_recursion_limit(tmp_path: Path) -> None:
    depth = 1200
    expr = "(" * depth + "1" + ")" * depth
    _write(tmp_path, "deep.py", f"def f():\n    return {expr}\n")
    analysis = analyze_repo(tmp_path)
    assert "deep" in analysis.modules
