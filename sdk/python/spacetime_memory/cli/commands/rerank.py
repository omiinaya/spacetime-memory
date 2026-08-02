"""CLI commands — multi-reranker search (Gap #4)."""
from __future__ import annotations

import json
from typing import Any

import click

from spacetime_memory.client._rerank import (
    CrossEncoderReranker,
    FusionReranker,
    MMRReranker,
    NodeDistanceReranker,
    SearchFilter,
    list_recipes,
    resolve_recipe,
)

from ..root import (
    _quiet_print,
    _sdk_client,
    cli,
    console,
    print_json,
    print_table,
)

# ── stmem search command ──────────────────────────────────────────────


@cli.command()
@click.argument("workspace_id")
@click.argument("query")
@click.option("--strategy", "-s", default="hybrid",
              type=click.Choice(["keyword", "semantic", "hybrid", "temporal",
                                 "graph", "entity", "boolean", "fuzzy"]),
              help="Search strategy (default: hybrid)")
@click.option("--filter", "-f", "filter_str", default="",
              help="Filter DSL string, e.g. 'node_labels:[\"Person\"]'")
@click.option("--reranker", "-r", default="",
              type=click.Choice(["cross-encoder", "mmr", "node-distance",
                                 "fusion", ""]),
              help="Reranker to apply after search")
@click.option("--top-k", default=20, type=int, help="Max results to return")
@click.option("--recipe", "-p", default="",
              help="Named search recipe (overrides --strategy/--reranker)")
@click.option("--recipe-param", multiple=True,
              help="Recipe parameter overrides, e.g. 'top_k=15'")
@click.option("--llm-rerank/--no-llm-rerank", "use_llm_rerank",
              default=False,
              help="Apply LLM reranking after other rerankers")
@click.pass_context
def search(
    ctx: click.Context,
    workspace_id: str,
    query: str,
    strategy: str,
    filter_str: str,
    reranker: str,
    top_k: int,
    recipe: str,
    recipe_param: tuple[str, ...],
    use_llm_rerank: bool,
) -> None:
    """Search across all stores (memories, KG, notes).

    WORKSPACE_ID is the target workspace.

    QUERY is the search query string.

    Examples:

      stmem search ws1 "machine learning"

      stmem search ws1 "deep learning" --strategy semantic --top-k 15

      stmem search ws1 "AI safety" --recipe question_answering

      stmem search ws1 "Alice" --filter 'node_labels:["Person"]'

      stmem search ws1 "transformer" --reranker mmr --top-k 10

      stmem search ws1 "recent updates" --strategy temporal --filter 'temporal:{"after": 1700000000}'
    """
    client = _sdk_client()

    # Resolve filter
    parsed_filter: SearchFilter | None = None
    if filter_str:
        try:
            parsed_filter = SearchFilter.parse(filter_str)
        except Exception as e:
            console.print(f"[red]Invalid filter DSL: {e}[/red]")
            return

    # Resolve recipe if provided
    active_reranker_name = reranker
    active_top_k = top_k

    if recipe:
        resolved = resolve_recipe(recipe)
        if resolved is None:
            names = [r["name"] for r in list_recipes()]
            _quiet_print(f"[yellow]Unknown recipe '{recipe}'. Available: {', '.join(names)}[/yellow]")
            return
        strategy = resolved.strategy
        active_top_k = resolved.top_k
        if resolved.reranker:
            active_reranker_name = resolved.reranker

    # Map strategy to client.search() kwargs
    search_kwargs: dict[str, Any] = {
        "workspace_id": workspace_id,
        "query": query,
        "limit": active_top_k,
    }

    if strategy == "keyword":
        search_kwargs["semantic"] = False
    elif strategy == "semantic" or strategy == "hybrid" or strategy == "temporal" or strategy in ("graph", "entity"):
        search_kwargs["semantic"] = True

    # Apply temporal filter if set
    if parsed_filter:
        if parsed_filter.temporal_after is not None:
            search_kwargs["after"] = parsed_filter.temporal_after
        if parsed_filter.temporal_before is not None:
            search_kwargs["before"] = parsed_filter.temporal_before

    # Execute search via client
    with console.status(f"Searching (strategy={strategy})..."):
        try:
            results = client.search(**search_kwargs)
        except Exception as e:
            console.print(f"[red]Search failed: {e}[/red]")
            return

    if not results:
        _quiet_print("[yellow]No results found.[/yellow]")
        return

    # Apply post-filtering for node_labels / edge_types
    if parsed_filter:
        if parsed_filter.node_labels:
            results = [
                r for r in results
                if r.get("label", "").lower() in (lab.lower() for lab in parsed_filter.node_labels)
                or r.get("node_type", "").lower() in (lab.lower() for lab in parsed_filter.node_labels)
            ]
        if parsed_filter.edge_types:
            results = [
                r for r in results
                if r.get("relation", "").lower() in (e.lower() for e in parsed_filter.edge_types)
            ]

    if not results:
        _quiet_print("[yellow]No results after filtering.[/yellow]")
        return

    # Apply reranker
    if active_reranker_name:
        with console.status(f"Reranking with '{active_reranker_name}'..."):
            try:
                if active_reranker_name == "cross-encoder":
                    reranker_obj = CrossEncoderReranker()
                    results = reranker_obj.rerank(query, results, top_k=active_top_k)
                elif active_reranker_name == "mmr":
                    reranker_obj = MMRReranker()
                    results = reranker_obj.rerank(query, results, top_k=active_top_k)
                elif active_reranker_name == "node-distance":
                    reranker_obj = NodeDistanceReranker(client=client)
                    results = reranker_obj.rerank(
                        query, results,
                        top_k=active_top_k,
                        workspace_id=workspace_id,
                    )
                elif active_reranker_name == "fusion":
                    reranker_obj = FusionReranker()
                    ce = CrossEncoderReranker()
                    nd = NodeDistanceReranker(client=client)
                    reranker_obj.add(ce, weight=0.6).add(nd, weight=0.4)
                    results = reranker_obj.rerank(
                        query, results,
                        top_k=active_top_k,
                        workspace_id=workspace_id,
                    )
            except Exception as e:
                console.print(f"[red]Reranking failed: {e}[/red]")

    # Apply LLM rerank if requested
    if use_llm_rerank:
        from spacetime_memory.client._rerank import llm_rerank as _llm_fn
        with console.status("Applying LLM rerank..."):
            try:
                results = _llm_fn(query, results, top_k=active_top_k)
            except Exception as e:
                console.print(f"[yellow]LLM rerank failed (continuing): {e}[/yellow]")

    # Trim to top_k
    results = results[:active_top_k]

    # Display
    output = ctx.obj.get("output", "table")
    if output == "json":
        print_json(results)
    else:
        display_rows = []
        for i, r in enumerate(results):
            content = r.get("memory_content") or r.get("content") or ""
            score = r.get("score", r.get("fused_score", 0.0))
            display_rows.append({
                "#": i + 1,
                "Score": f"{float(score):.4f}",
                "Entity": r.get("entity_id", "")[:16],
                "Type": r.get("entity_type", ""),
                "Snippet": content[:120],
            })
        print_table(
            display_rows,
            title=f"Search Results (workspace: {workspace_id})",
            output=output,
        )


# ── stmem recipes sub-command ──────────────────────────────────────────


@cli.group()
def recipes() -> None:
    """Manage and list search recipes.

    Recipes are named search configurations that bundle strategy, reranker,
    and filter settings.

    Examples:

      stmem recipes list

      stmem recipes show question_answering
    """


@recipes.command(name="list")
@click.pass_context
def recipes_list(ctx: click.Context) -> None:
    """List all available search recipes."""
    output = ctx.obj.get("output", "table")
    recipes_data = list_recipes()
    print_table(
        recipes_data,
        title="Search Recipes",
        output=output,
    )


@recipes.command(name="show")
@click.argument("name")
@click.pass_context
def recipes_show(ctx: click.Context, name: str) -> None:
    """Show details of a specific recipe.

    NAME is the recipe name (e.g. question_answering).
    """
    recipe = resolve_recipe(name)
    if recipe is None:
        _quiet_print(f"[red]Recipe '{name}' not found. Use 'stmem recipes list' to see available recipes.[/red]")
        return

    output = ctx.obj.get("output", "table")
    details = {
        "name": recipe.name,
        "description": recipe.description,
        "strategy": recipe.strategy,
        "reranker": recipe.reranker or "(none)",
        "reranker_params": json.dumps(recipe.reranker_params) if recipe.reranker_params else "",
        "top_k": recipe.top_k,
        "filter_dsl": recipe.filter_dsl or "(none)",
    }
    if output == "json":
        print_json(details)
    else:
        _quiet_print(f"[bold cyan]Recipe: {recipe.name}[/bold cyan]")
        _quiet_print(f"  Description: {recipe.description}")
        _quiet_print(f"  Strategy:    {recipe.strategy}")
        _quiet_print(f"  Reranker:    {recipe.reranker or '(none)'}")
        _quiet_print(f"  Top-K:       {recipe.top_k}")
        if recipe.reranker_params:
            _quiet_print(f"  Reranker params: {json.dumps(recipe.reranker_params)}")
        if recipe.filter_dsl:
            _quiet_print(f"  Filter DSL:  {recipe.filter_dsl}")
        if recipe.kwargs:
            _quiet_print(f"  Extra kwargs: {json.dumps(recipe.kwargs)}")
