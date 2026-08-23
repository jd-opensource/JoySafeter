use std::collections::{BTreeMap, BTreeSet, HashMap, HashSet};
use std::fs;
use std::path::{Path, PathBuf};

use proc_macro2::{TokenStream, TokenTree};
use syn::parse::Parser;
use syn::punctuated::Punctuated;
use syn::visit::{self, Visit};
use syn::{Attribute, Expr, Item, Lit, Macro, Meta, Pat, Token, UseTree};

const MANAGED_CREDENTIAL_TABLES: [&str; 3] = [
    "joysafeter_credentials",
    "joysafeter_credential_groups",
    "joysafeter_session_credential_groups",
];

#[test]
fn production_managed_credential_sql_is_owned_by_the_store() {
    let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let source_root = manifest_dir.join("src");
    let lib_root = source_root.join("lib.rs");
    let main_root = source_root.join("main.rs");
    let allowed = source_root
        .join("kernel/credentials/store.rs")
        .canonicalize()
        .expect("canonical Store path");
    // Reviewed non-Store Managed Credential SQL. Envelope inventory/canary
    // validation lives in the sensitive-material module rather than the Store: it
    // aggregates ciphertext envelope versions and key ids to prove key-rotation
    // coverage, never selects plaintext, and never participates in runtime
    // credential resolution. Kept as an explicit owned exception so the
    // Store-ownership rule still fails closed for any other credential SQL.
    let reviewed_non_store: Vec<PathBuf> = ["kernel/sensitive_material/versioned.rs"]
        .into_iter()
        .map(|rel| {
            source_root
                .join(rel)
                .canonicalize()
                .expect("canonical reviewed non-Store path")
        })
        .collect();
    let inventory = RustCompileInventory::scan_roots(&[lib_root.clone(), main_root.clone()]);

    assert!(
        inventory.unresolved.is_empty(),
        "Rust SQL inventory failed closed:\n{}",
        inventory.unresolved.join("\n")
    );
    for root in [lib_root, main_root] {
        assert!(
            inventory
                .visited
                .contains(&root.canonicalize().expect("canonical production root")),
            "production root was not scanned: {}",
            root.display()
        );
    }
    assert!(
        inventory
            .credential_sql
            .iter()
            .any(|finding| finding.path == allowed),
        "inventory must observe Store SQL and may not be vacuous"
    );
    let violations = inventory
        .credential_sql
        .into_iter()
        .filter(|finding| finding.path != allowed && !reviewed_non_store.contains(&finding.path))
        .collect::<Vec<_>>();
    assert!(
        violations.is_empty(),
        "production Managed Credential SQL must live only in {} (or a reviewed sensitive-material exception):\n{}",
        allowed.display(),
        violations
            .iter()
            .map(SqlFinding::display)
            .collect::<Vec<_>>()
            .join("\n")
    );
}

#[test]
fn inventory_starts_from_lib_and_main_and_skips_pure_test_cfg() {
    let temp = tempfile::tempdir().expect("create fixture directory");
    let lib_root = temp.path().join("lib.rs");
    let main_root = temp.path().join("main.rs");
    let production = temp.path().join("production.rs");
    let included = temp.path().join("included_expr.rs");
    fs::write(
        &lib_root,
        r#"
        mod production;
        #[cfg(test)]
        mod tests {
            fn fixture() {
                let _ = sqlx::query("SELECT * FROM joysafeter_credentials");
            }
        }
        "#,
    )
    .expect("write lib fixture");
    fs::write(&main_root, "fn main() {}\n").expect("write main fixture");
    fs::write(
        &production,
        r#"
        fn production() {
            include!("included_expr.rs");
        }
        "#,
    )
    .expect("write production module fixture");
    fs::write(
        &included,
        r#"
        {
            let _ = sqlx::query("SELECT * FROM joysafeter_credentials");
        }
        "#,
    )
    .expect("write included expression fixture");

    let inventory = RustCompileInventory::scan_roots(&[lib_root, main_root]);

    assert!(inventory.unresolved.is_empty());
    assert_eq!(inventory.credential_sql.len(), 1);
    assert_eq!(
        inventory.credential_sql[0].path,
        included.canonicalize().expect("canonical included fixture")
    );
}

#[test]
fn inventory_fails_closed_for_alias_builder_wrapper_split_and_cfg_attr_inputs() {
    let cases = [
        (
            "alias.rs",
            r#"
            use sqlx::query as run;
            fn production() {
                let _ = run(concat!("SELECT * FROM joysafeter_", "credentials"));
            }
            "#,
        ),
        (
            "builder.rs",
            r#"
            fn production() {
                let mut query = sqlx::QueryBuilder::new("SELECT * FROM ");
                query.push("joysafeter_");
                query.push("credential_groups");
            }
            "#,
        ),
        (
            "builder_alias.rs",
            r#"
            use sqlx::QueryBuilder as Builder;
            fn production() {
                let mut query = Builder::new("SELECT * FROM ");
                query.push("joysafeter_");
                query.push("credential_groups");
            }
            "#,
        ),
        (
            "wrapper.rs",
            r#"
            macro_rules! run_sql {
                ($sql:expr) => { sqlx::query($sql) };
            }
            fn production() {
                let _ = run_sql!(concat!("SELECT * FROM joysafeter_session_", "credential_groups"));
            }
            "#,
        ),
        (
            "dynamic.rs",
            r#"
            fn production(table: &str) {
                let _ = sqlx::query(&format!("SELECT * FROM {table}"));
            }
            "#,
        ),
        (
            "cfg_attr.rs",
            r#"
            #[cfg_attr(feature = "alternate", path = "alternate.rs")]
            mod production;
            "#,
        ),
    ];

    for (name, source) in cases {
        let temp = tempfile::tempdir().expect("create fixture directory");
        let root = temp.path().join("lib.rs");
        fs::write(&root, source).expect("write bypass fixture");
        let inventory = RustCompileInventory::scan_roots(&[root]);
        assert!(
            !inventory.credential_sql.is_empty() || !inventory.unresolved.is_empty(),
            "{name} bypass must fail closed"
        );
    }
}

#[test]
fn inventory_rejects_dynamic_sql_even_under_former_session_builder_paths() {
    let temp = tempfile::tempdir().expect("create fixture directory");
    let source_dir = temp.path().join("src/db/queries");
    fs::create_dir_all(&source_dir).expect("create source fixture directory");
    let root = source_dir.join("session.rs");
    fs::write(
        &root,
        r#"
        fn production(table: &str) {
            let sql = format!("SELECT * FROM joysafeter_{table}");
            let _ = sqlx::query(&sql);
        }
        "#,
    )
    .expect("write former exception fixture");

    let inventory = RustCompileInventory::scan_roots(&[root]);

    assert_eq!(inventory.unresolved.len(), 1);
    assert!(inventory.unresolved[0].contains("non-static SQL input"));
}

#[test]
fn inventory_analyzes_renamed_and_arbitrary_static_sql_factories() {
    let temp = tempfile::tempdir().expect("create fixture directory");
    let root = temp.path().join("lib.rs");
    fs::write(
        &root,
        r#"
        fn renamed_factory(use_managed: bool) -> String {
            let table = if use_managed {
                "joysafeter_credentials"
            } else {
                "unmanaged_records"
            };
            let prefix = "SELECT * FROM ";
            format!("{prefix}{table}")
        }

        fn production() {
            let _ = sqlx::query(&renamed_factory(true));
            let _ = sqlx::query(&arbitrary_factory());
        }

        fn arbitrary_factory() -> String {
            let table = concat!("joysafeter_", "credential_groups");
            format!("SELECT * FROM {table}")
        }
        "#,
    )
    .expect("write generic factory fixture");

    let inventory = RustCompileInventory::scan_roots(&[root]);

    assert!(
        inventory.unresolved.is_empty(),
        "{:?}",
        inventory.unresolved
    );
    let observed_tables = inventory
        .credential_sql
        .iter()
        .flat_map(|finding| finding.tables.iter().copied())
        .collect::<BTreeSet<_>>();
    assert!(observed_tables.contains("joysafeter_credentials"));
    assert!(observed_tables.contains("joysafeter_credential_groups"));
}

#[test]
fn inventory_rejects_dynamic_factory_tables_and_unknown_wrappers() {
    let cases = [
        (
            "dynamic_factory.rs",
            r#"
            fn dynamic_factory(table: &str) -> String {
                format!("SELECT * FROM {table}")
            }
            fn production(table: &str) {
                let _ = sqlx::query(&dynamic_factory(table));
            }
            "#,
        ),
        (
            "unknown_wrapper.rs",
            r#"
            fn wrapper(sql: &str) -> String {
                opaque_runtime_transform(sql)
            }
            fn production() {
                let _ = sqlx::query(&wrapper("SELECT * FROM joysafeter_credentials"));
            }
            "#,
        ),
    ];

    for (name, source) in cases {
        let temp = tempfile::tempdir().expect("create fixture directory");
        let root = temp.path().join("lib.rs");
        fs::write(&root, source).expect("write dynamic factory fixture");

        let inventory = RustCompileInventory::scan_roots(&[root]);

        assert_eq!(
            inventory.unresolved.len(),
            1,
            "{name}: {:?}",
            inventory.unresolved
        );
        assert!(inventory.unresolved[0].contains("non-static SQL input"));
    }
}

#[test]
fn inventory_rejects_dynamic_query_input() {
    let temp = tempfile::tempdir().expect("create fixture directory");
    let root = temp.path().join("lib.rs");
    fs::write(
        &root,
        r#"
        fn production(sql: &str) {
            let _ = sqlx::query(sql);
        }
        "#,
    )
    .expect("write fixture");

    let inventory = RustCompileInventory::scan_roots(&[root]);

    assert_eq!(inventory.unresolved.len(), 1);
    assert!(inventory.unresolved[0].contains("non-static SQL input"));
}

#[test]
fn inventory_invalidates_shadowed_static_sql_bindings() {
    let temp = tempfile::tempdir().expect("create fixture directory");
    let root = temp.path().join("lib.rs");
    fs::write(
        &root,
        r#"
        fn production(runtime_table: &str) {
            let table = "unmanaged_records";
            let table = runtime_table;
            let _ = sqlx::query(&format!("SELECT * FROM {table}"));
        }
        "#,
    )
    .expect("write shadowing fixture");

    let inventory = RustCompileInventory::scan_roots(&[root]);

    assert_eq!(inventory.credential_sql.len(), 0);
    assert_eq!(inventory.unresolved.len(), 1, "{:?}", inventory.unresolved);
    assert!(inventory.unresolved[0].contains("dynamic SQL binding `table`"));
}

#[test]
fn inventory_invalidates_assigned_static_sql_bindings() {
    let temp = tempfile::tempdir().expect("create fixture directory");
    let root = temp.path().join("lib.rs");
    fs::write(
        &root,
        r#"
        fn production(runtime_table: &str) {
            let mut table = "unmanaged_records";
            table = runtime_table;
            let _ = sqlx::query(&format!("SELECT * FROM {table}"));
        }
        "#,
    )
    .expect("write assignment fixture");

    let inventory = RustCompileInventory::scan_roots(&[root]);

    assert_eq!(inventory.credential_sql.len(), 0);
    assert_eq!(inventory.unresolved.len(), 1, "{:?}", inventory.unresolved);
    assert!(inventory.unresolved[0].contains("dynamic SQL binding `table`"));
}

#[test]
fn inventory_invalidates_shadowed_bindings_inside_sql_factories() {
    let temp = tempfile::tempdir().expect("create fixture directory");
    let root = temp.path().join("lib.rs");
    fs::write(
        &root,
        r#"
        fn factory(runtime_table: &str) -> String {
            let table = "unmanaged_records";
            let table = runtime_table;
            format!("SELECT * FROM {table}")
        }

        fn production(runtime_table: &str) {
            let _ = sqlx::query(&factory(runtime_table));
        }
        "#,
    )
    .expect("write factory shadowing fixture");

    let inventory = RustCompileInventory::scan_roots(&[root]);

    assert_eq!(inventory.credential_sql.len(), 0);
    assert_eq!(inventory.unresolved.len(), 1, "{:?}", inventory.unresolved);
    assert!(inventory.unresolved[0].contains("dynamic SQL binding `table`"));
}

#[test]
fn inventory_rejects_dynamic_raw_sql_input() {
    let temp = tempfile::tempdir().expect("create fixture directory");
    let root = temp.path().join("lib.rs");
    fs::write(
        &root,
        r#"
        fn production(table: &str) {
            let _ = sqlx::raw_sql(&format!("SELECT * FROM {table}"));
        }
        "#,
    )
    .expect("write raw_sql fixture");

    let inventory = RustCompileInventory::scan_roots(&[root]);

    assert_eq!(inventory.credential_sql.len(), 0);
    assert_eq!(inventory.unresolved.len(), 1, "{:?}", inventory.unresolved);
    assert!(inventory.unresolved[0].contains("non-static SQL input"));
}

#[test]
fn inventory_reads_managed_sql_from_query_file_macros() {
    let temp = tempfile::tempdir().expect("create fixture directory");
    let root = temp.path().join("lib.rs");
    fs::write(
        &root,
        r#"
        fn production() {
            let _ = sqlx::query_file!("managed.sql");
        }
        "#,
    )
    .expect("write query_file fixture");
    fs::write(
        temp.path().join("managed.sql"),
        "SELECT * FROM joysafeter_credentials",
    )
    .expect("write SQL file fixture");

    let inventory = RustCompileInventory::scan_roots(&[root]);

    assert!(
        inventory.unresolved.is_empty(),
        "{:?}",
        inventory.unresolved
    );
    assert_eq!(inventory.credential_sql.len(), 1);
    assert!(inventory.credential_sql[0]
        .tables
        .contains("joysafeter_credentials"));
}

#[test]
fn inventory_resolves_alias_backed_sql_wrapper_macros() {
    let temp = tempfile::tempdir().expect("create fixture directory");
    let root = temp.path().join("lib.rs");
    fs::write(
        &root,
        r#"
        use sqlx::query as run;

        macro_rules! wrapper {
            ($sql:expr) => { run($sql) };
        }

        fn production() {
            let _ = wrapper!(concat!("SELECT * FROM joysafeter_", "credential_groups"));
        }
        "#,
    )
    .expect("write alias-backed wrapper fixture");

    let inventory = RustCompileInventory::scan_roots(&[root]);

    assert!(
        inventory.unresolved.is_empty(),
        "{:?}",
        inventory.unresolved
    );
    assert_eq!(inventory.credential_sql.len(), 1);
    assert!(inventory.credential_sql[0]
        .tables
        .contains("joysafeter_credential_groups"));
}

#[test]
fn inventory_invalidates_compound_assigned_static_sql_bindings() {
    let temp = tempfile::tempdir().expect("create fixture directory");
    let root = temp.path().join("lib.rs");
    fs::write(
        &root,
        r#"
        fn production(runtime_fragment: &str) {
            let mut sql = format!("SELECT * FROM unmanaged_records");
            sql += runtime_fragment;
            let _ = sqlx::query(&sql);
        }
        "#,
    )
    .expect("write compound-assignment fixture");

    let inventory = RustCompileInventory::scan_roots(&[root]);

    assert_eq!(inventory.credential_sql.len(), 0);
    assert_eq!(inventory.unresolved.len(), 1, "{:?}", inventory.unresolved);
    assert!(inventory.unresolved[0].contains("dynamic SQL binding `sql`"));
}

#[test]
fn inventory_invalidates_push_str_mutated_static_sql_bindings() {
    let temp = tempfile::tempdir().expect("create fixture directory");
    let root = temp.path().join("lib.rs");
    fs::write(
        &root,
        r#"
        fn production(runtime_fragment: &str) {
            let mut sql = format!("SELECT * FROM unmanaged_records");
            sql.push_str(runtime_fragment);
            let _ = sqlx::query(&sql);
        }
        "#,
    )
    .expect("write push_str fixture");

    let inventory = RustCompileInventory::scan_roots(&[root]);

    assert_eq!(inventory.credential_sql.len(), 0);
    assert_eq!(inventory.unresolved.len(), 1, "{:?}", inventory.unresolved);
    assert!(inventory.unresolved[0].contains("dynamic SQL binding `sql`"));
}

#[test]
fn inventory_invalidates_mutations_hidden_inside_sql_factories() {
    let temp = tempfile::tempdir().expect("create fixture directory");
    let root = temp.path().join("lib.rs");
    fs::write(
        &root,
        r#"
        fn factory(runtime_fragment: &str) -> String {
            let mut sql = format!("SELECT * FROM unmanaged_records");
            let _ = sql.push_str(runtime_fragment);
            sql
        }

        fn production(runtime_fragment: &str) {
            let _ = sqlx::query(&factory(runtime_fragment));
        }
        "#,
    )
    .expect("write factory mutation fixture");

    let inventory = RustCompileInventory::scan_roots(&[root]);

    assert_eq!(inventory.credential_sql.len(), 0);
    assert_eq!(inventory.unresolved.len(), 1, "{:?}", inventory.unresolved);
    assert!(inventory.unresolved[0].contains("dynamic SQL binding `sql`"));
}

#[test]
fn inventory_invalidates_factory_bindings_used_by_initializer_macros() {
    let temp = tempfile::tempdir().expect("create fixture directory");
    let root = temp.path().join("lib.rs");
    fs::write(
        &root,
        r#"
        macro_rules! mutate {
            ($sql:expr, $fragment:expr) => { $sql.push_str($fragment) };
        }

        fn factory(runtime_fragment: &str) -> String {
            let mut sql = format!("SELECT * FROM unmanaged_records");
            let _ = mutate!(sql, runtime_fragment);
            sql
        }

        fn production(runtime_fragment: &str) {
            let _ = sqlx::query(&factory(runtime_fragment));
        }
        "#,
    )
    .expect("write factory initializer macro mutation fixture");

    let inventory = RustCompileInventory::scan_roots(&[root]);

    assert_eq!(inventory.credential_sql.len(), 0);
    assert_eq!(inventory.unresolved.len(), 1, "{:?}", inventory.unresolved);
    assert!(inventory.unresolved[0].contains("dynamic SQL binding `sql`"));
}

#[test]
fn inventory_invalidates_tracked_bindings_passed_to_unknown_macros() {
    let temp = tempfile::tempdir().expect("create fixture directory");
    let root = temp.path().join("lib.rs");
    fs::write(
        &root,
        r#"
        macro_rules! append_runtime {
            ($sql:expr, $fragment:expr) => { $sql.push_str($fragment) };
        }

        fn production(runtime_fragment: &str) {
            let mut sql = format!("SELECT * FROM unmanaged_records");
            append_runtime!(sql, runtime_fragment);
            let _ = sqlx::query(&sql);
        }
        "#,
    )
    .expect("write unknown macro mutation fixture");

    let inventory = RustCompileInventory::scan_roots(&[root]);

    assert_eq!(inventory.credential_sql.len(), 0);
    assert_eq!(inventory.unresolved.len(), 1, "{:?}", inventory.unresolved);
    assert!(inventory.unresolved[0].contains("dynamic SQL binding `sql`"));
}

#[test]
fn inventory_resolves_crate_alias_direct_sqlx_calls() {
    let temp = tempfile::tempdir().expect("create fixture directory");
    let root = temp.path().join("lib.rs");
    fs::write(
        &root,
        r#"
        use sqlx as db;

        fn production(sql: &str) {
            let _ = db::query(sql);
            let _ = db::raw_sql(sql);
        }
        "#,
    )
    .expect("write crate-alias direct-call fixture");

    let inventory = RustCompileInventory::scan_roots(&[root]);

    assert_eq!(inventory.credential_sql.len(), 0);
    assert_eq!(inventory.unresolved.len(), 2, "{:?}", inventory.unresolved);
    assert!(inventory
        .unresolved
        .iter()
        .all(|error| error.contains("non-static SQL input")));
}

#[test]
fn inventory_resolves_crate_alias_backed_sql_wrapper_macros() {
    let temp = tempfile::tempdir().expect("create fixture directory");
    let root = temp.path().join("lib.rs");
    fs::write(
        &root,
        r#"
        use sqlx as db;

        macro_rules! wrapper {
            ($sql:expr) => { db::query($sql) };
        }

        fn production() {
            let _ = wrapper!(concat!("SELECT * FROM joysafeter_", "credentials"));
        }
        "#,
    )
    .expect("write crate-alias wrapper fixture");

    let inventory = RustCompileInventory::scan_roots(&[root]);

    assert!(
        inventory.unresolved.is_empty(),
        "{:?}",
        inventory.unresolved
    );
    assert_eq!(inventory.credential_sql.len(), 1);
    assert!(inventory.credential_sql[0]
        .tables
        .contains("joysafeter_credentials"));
}

#[test]
fn inventory_resolves_function_local_sqlx_aliases() {
    let temp = tempfile::tempdir().expect("create fixture directory");
    let root = temp.path().join("lib.rs");
    fs::write(
        &root,
        r#"
        fn production(sql: &str) {
            use sqlx::raw_sql as run;
            macro_rules! wrapper {
                ($sql:expr) => { run($sql) };
            }
            let _ = run(sql);
            let _ = wrapper!(sql);
        }
        "#,
    )
    .expect("write function-local alias fixture");

    let inventory = RustCompileInventory::scan_roots(&[root]);

    assert_eq!(inventory.credential_sql.len(), 0);
    assert_eq!(inventory.unresolved.len(), 2, "{:?}", inventory.unresolved);
    assert!(inventory
        .unresolved
        .iter()
        .all(|error| error.contains("non-static SQL input")));
}

#[test]
fn inventory_resolves_executor_raw_sql_methods() {
    let temp = tempfile::tempdir().expect("create fixture directory");
    let root = temp.path().join("lib.rs");
    fs::write(
        &root,
        r#"
        fn production(pool: &sqlx::PgPool, sql: &str) {
            let _ = pool.execute(sql);
            let _ = pool.fetch_all(sql);
            let _ = pool.prepare(sql);
        }
        "#,
    )
    .expect("write Executor method fixture");

    let inventory = RustCompileInventory::scan_roots(&[root]);

    assert_eq!(inventory.credential_sql.len(), 0);
    assert_eq!(inventory.unresolved.len(), 3, "{:?}", inventory.unresolved);
    assert!(inventory
        .unresolved
        .iter()
        .all(|error| error.contains("non-static SQL input")));
}

#[test]
fn inventory_does_not_treat_query_terminal_methods_as_raw_sql_inputs() {
    let temp = tempfile::tempdir().expect("create fixture directory");
    let root = temp.path().join("lib.rs");
    fs::write(
        &root,
        r#"
        fn production(pool: &sqlx::PgPool) {
            let _ = sqlx::query("SELECT * FROM unmanaged_records").execute(pool);
            let query = sqlx::query("SELECT * FROM unmanaged_records").bind(1_i64);
            let _ = query.fetch_all(pool);
            let query_for_executor = sqlx::query("SELECT * FROM unmanaged_records");
            let _ = pool.execute(query_for_executor);
        }
        "#,
    )
    .expect("write query terminal fixture");

    let inventory = RustCompileInventory::scan_roots(&[root]);

    assert!(
        inventory.unresolved.is_empty(),
        "{:?}",
        inventory.unresolved
    );
    assert!(inventory.credential_sql.is_empty());
}

#[test]
fn inventory_fails_closed_for_imported_sqlx_macro_aliases() {
    let temp = tempfile::tempdir().expect("create fixture directory");
    let root = temp.path().join("lib.rs");
    fs::write(
        &root,
        r#"
        use sqlx::query as run;

        fn production() {
            let _ = run!("SELECT * FROM joysafeter_credentials");
        }
        "#,
    )
    .expect("write imported SQLx macro alias fixture");

    let inventory = RustCompileInventory::scan_roots(&[root]);

    assert_eq!(inventory.credential_sql.len(), 0);
    assert_eq!(inventory.unresolved.len(), 1, "{:?}", inventory.unresolved);
    assert!(inventory.unresolved[0].contains("unrecognized SQLx execution/query macro"));
}

#[test]
fn inventory_rejects_unknown_sqlx_surfaces_through_crate_aliases() {
    let temp = tempfile::tempdir().expect("create fixture directory");
    let root = temp.path().join("lib.rs");
    fs::write(
        &root,
        r#"
        use sqlx as db;

        fn production(sql: &str) {
            let _ = db::query_future(sql);
            let _ = db::execute_future!(sql);
        }
        "#,
    )
    .expect("write unknown crate-alias SQLx surface fixture");

    let inventory = RustCompileInventory::scan_roots(&[root]);

    assert_eq!(inventory.credential_sql.len(), 0);
    assert_eq!(inventory.unresolved.len(), 2, "{:?}", inventory.unresolved);
    assert!(inventory
        .unresolved
        .iter()
        .all(|error| error.contains("unrecognized SQLx execution/query")));
}

#[test]
fn inventory_respects_function_parameter_shadowing_of_sqlx_aliases() {
    let temp = tempfile::tempdir().expect("create fixture directory");
    let root = temp.path().join("lib.rs");
    fs::write(
        &root,
        r#"
        use sqlx::query as run;

        fn production(run: impl Fn(&str), runtime_value: &str) {
            run(runtime_value);
        }
        "#,
    )
    .expect("write function parameter shadowing fixture");

    let inventory = RustCompileInventory::scan_roots(&[root]);

    assert!(
        inventory.unresolved.is_empty(),
        "{:?}",
        inventory.unresolved
    );
    assert!(inventory.credential_sql.is_empty());
}

#[test]
fn inventory_keeps_sqlx_aliases_lexical_to_their_modules() {
    let temp = tempfile::tempdir().expect("create fixture directory");
    let root = temp.path().join("lib.rs");
    fs::write(
        &root,
        r#"
        mod sql_scope {
            use sqlx::query as run;

            fn production() {
                let _ = run("SELECT * FROM unmanaged_records");
            }
        }

        mod unrelated_scope {
            fn run(_value: &str) {}

            macro_rules! wrapper {
                ($value:expr) => { run($value) };
            }

            fn production(runtime_value: &str) {
                wrapper!(runtime_value);
            }
        }
        "#,
    )
    .expect("write sibling-module alias fixture");

    let inventory = RustCompileInventory::scan_roots(&[root]);

    assert!(
        inventory.unresolved.is_empty(),
        "{:?}",
        inventory.unresolved
    );
    assert!(inventory.credential_sql.is_empty());
}

#[test]
fn inventory_propagates_parent_sql_wrapper_macros_into_nested_modules() {
    let temp = tempfile::tempdir().expect("create fixture directory");
    let root = temp.path().join("lib.rs");
    fs::write(
        &root,
        r#"
        macro_rules! wrapper {
            ($sql:expr) => { sqlx::query($sql) };
        }

        mod child {
            fn production() {
                let _ = wrapper!(concat!("SELECT * FROM joysafeter_", "credentials"));
            }
        }

        mod sibling {
            fn wrapper(_value: &str) {}

            fn production(runtime_value: &str) {
                wrapper(runtime_value);
            }
        }
        "#,
    )
    .expect("write parent wrapper nested-module fixture");

    let inventory = RustCompileInventory::scan_roots(&[root]);

    assert!(
        inventory.unresolved.is_empty(),
        "{:?}",
        inventory.unresolved
    );
    assert_eq!(inventory.credential_sql.len(), 1);
    assert!(inventory.credential_sql[0]
        .tables
        .contains("joysafeter_credentials"));
}

#[derive(Debug)]
struct SqlFinding {
    path: PathBuf,
    line: usize,
    tables: BTreeSet<&'static str>,
}

impl SqlFinding {
    fn display(&self) -> String {
        format!(
            "{}:{} [{}]",
            self.path.display(),
            self.line,
            self.tables.iter().copied().collect::<Vec<_>>().join(", ")
        )
    }
}

#[derive(Default)]
struct RustCompileInventory {
    visited: HashSet<PathBuf>,
    credential_sql: Vec<SqlFinding>,
    unresolved: Vec<String>,
    sql_factories: HashMap<String, Vec<SqlFactory>>,
    compile_inputs: BTreeMap<PathBuf, CompileInput>,
    sqlx_query_roots: Vec<PathBuf>,
}

#[derive(Clone)]
struct SqlFactory {
    parameters: Vec<String>,
    body: syn::Block,
}

#[derive(Clone)]
enum CompileInput {
    File {
        source: String,
        file: syn::File,
        module_dir: PathBuf,
    },
    Expression {
        source: String,
        expression: Expr,
    },
    Block {
        source: String,
        block: syn::Block,
    },
}

impl RustCompileInventory {
    fn scan_roots(roots: &[PathBuf]) -> Self {
        let mut inventory = Self::default();
        inventory.sqlx_query_roots = roots
            .iter()
            .map(|root| sqlx_manifest_root(root))
            .collect::<BTreeSet<_>>()
            .into_iter()
            .collect();
        for root in roots {
            inventory.discover_file(root, module_dir_for(root));
        }
        inventory.register_compile_inputs();
        inventory.scan_compile_inputs();
        inventory
    }

    fn discover_file(&mut self, path: &Path, module_dir: PathBuf) {
        let path = match canonical_compile_input(path) {
            Ok(path) => path,
            Err(error) => {
                self.unresolved.push(error);
                return;
            }
        };
        if !self.visited.insert(path.clone()) {
            return;
        }
        let source = match fs::read_to_string(&path) {
            Ok(source) => source,
            Err(error) => {
                self.unresolved.push(format!(
                    "cannot read Rust compile input {}: {error}",
                    path.display()
                ));
                return;
            }
        };
        let file = match syn::parse_file(&source) {
            Ok(file) => file,
            Err(error) => {
                self.unresolved.push(format!(
                    "cannot parse Rust compile input {}: {error}",
                    path.display()
                ));
                return;
            }
        };
        self.compile_inputs.insert(
            path.clone(),
            CompileInput::File {
                source,
                file: file.clone(),
                module_dir: module_dir.clone(),
            },
        );
        self.discover_items(&path, &module_dir, &file.items);
    }

    fn discover_items(&mut self, path: &Path, module_dir: &Path, items: &[Item]) {
        for item in items {
            if is_test_only(item_attrs(item)) {
                continue;
            }
            match item {
                Item::Mod(module) => {
                    if let Some((_, nested)) = &module.content {
                        self.discover_items(
                            path,
                            &module_dir.join(module.ident.to_string()),
                            nested,
                        );
                    } else {
                        match resolve_module_path(path, module_dir, module) {
                            Ok(module_path) => {
                                let next_module_dir = module_dir_for(&module_path);
                                self.discover_file(&module_path, next_module_dir);
                            }
                            Err(error) => self.unresolved.push(error),
                        }
                    }
                }
                _ => {
                    let mut collector = IncludeCollector::default();
                    collector.visit_item(item);
                    for include in collector.inputs {
                        match compile_input_path(path, &include) {
                            Ok(include_path) => self.discover_included_input(&include_path),
                            Err(error) => self.unresolved.push(error),
                        }
                    }
                }
            }
        }
    }

    fn discover_included_input(&mut self, path: &Path) {
        let path = match canonical_compile_input(path) {
            Ok(path) => path,
            Err(error) => {
                self.unresolved.push(error);
                return;
            }
        };
        if !self.visited.insert(path.clone()) {
            return;
        }
        let source = match fs::read_to_string(&path) {
            Ok(source) => source,
            Err(error) => {
                self.unresolved.push(format!(
                    "cannot read included Rust compile input {}: {error}",
                    path.display()
                ));
                return;
            }
        };
        if let Ok(file) = syn::parse_file(&source) {
            let module_dir = module_dir_for(&path);
            self.compile_inputs.insert(
                path.clone(),
                CompileInput::File {
                    source,
                    file: file.clone(),
                    module_dir: module_dir.clone(),
                },
            );
            self.discover_items(&path, &module_dir, &file.items);
            return;
        }
        if let Ok(expression) = syn::parse_str::<Expr>(&source) {
            let mut collector = IncludeCollector::default();
            collector.visit_expr(&expression);
            self.compile_inputs.insert(
                path.clone(),
                CompileInput::Expression { source, expression },
            );
            self.discover_collected_includes(&path, collector.inputs);
            return;
        }
        if let Ok(block) = syn::parse_str::<syn::Block>(&source) {
            let mut collector = IncludeCollector::default();
            collector.visit_block(&block);
            self.compile_inputs
                .insert(path.clone(), CompileInput::Block { source, block });
            self.discover_collected_includes(&path, collector.inputs);
            return;
        }
        self.unresolved.push(format!(
            "cannot parse included Rust compile input {} as items, expression, or block",
            path.display()
        ));
    }

    fn discover_collected_includes(&mut self, path: &Path, inputs: Vec<Macro>) {
        for include in inputs {
            match compile_input_path(path, &include) {
                Ok(include_path) => self.discover_included_input(&include_path),
                Err(error) => self.unresolved.push(error),
            }
        }
    }

    fn register_compile_inputs(&mut self) {
        let files = self
            .compile_inputs
            .iter()
            .filter_map(|(path, input)| match input {
                CompileInput::File { file, .. } => Some((path.clone(), file.items.clone())),
                _ => None,
            })
            .collect::<Vec<_>>();
        for (path, items) in files {
            self.register_sql_factories(&path, &items);
        }
    }

    fn register_sql_factories(&mut self, path: &Path, items: &[Item]) {
        for item in items {
            if is_test_only(item_attrs(item)) {
                continue;
            }
            match item {
                Item::Fn(function) => match sql_factory(function) {
                    Ok(Some(factory)) => self
                        .sql_factories
                        .entry(function.sig.ident.to_string())
                        .or_default()
                        .push(factory),
                    Ok(None) => {}
                    Err(error) => self.unresolved.push(format!("{}: {error}", path.display())),
                },
                Item::Mod(module) => {
                    if let Some((_, nested)) = &module.content {
                        self.register_sql_factories(path, nested);
                    }
                }
                _ => {}
            }
        }
    }

    fn scan_items(
        &mut self,
        path: &Path,
        source: &str,
        module_dir: &Path,
        items: &[Item],
        outer: &SqlxNames,
    ) {
        let sqlx_scope = sqlx_scope_for_items(path, items, outer, &mut self.unresolved);
        let mut sqlx_names = outer.clone();
        sqlx_names.push_scope(sqlx_scope);

        for item in items {
            if is_test_only(item_attrs(item)) {
                continue;
            }
            if let Item::Mod(module) = item {
                if let Some((_, nested)) = &module.content {
                    self.scan_items(
                        path,
                        source,
                        &module_dir.join(module.ident.to_string()),
                        nested,
                        &sqlx_names,
                    );
                }
                continue;
            }

            let mut visitor = QueryVisitor::new(
                path,
                source,
                sqlx_names.clone(),
                self.sql_factories.clone(),
                self.sqlx_query_roots.clone(),
            );
            visitor.visit_item(item);
            self.absorb_visitor(visitor);
        }
    }

    fn absorb_visitor(&mut self, visitor: QueryVisitor<'_>) {
        self.credential_sql.extend(visitor.credential_sql);
        self.unresolved.extend(visitor.unresolved);
    }

    fn scan_compile_inputs(&mut self) {
        let inputs = self
            .compile_inputs
            .iter()
            .map(|(path, input)| (path.clone(), input.clone()))
            .collect::<Vec<_>>();
        for (path, input) in inputs {
            match input {
                CompileInput::File {
                    source,
                    file,
                    module_dir,
                } => self.scan_items(
                    &path,
                    &source,
                    &module_dir,
                    &file.items,
                    &SqlxNames::default(),
                ),
                CompileInput::Expression { source, expression } => {
                    let mut visitor = QueryVisitor::new(
                        &path,
                        &source,
                        SqlxNames::default(),
                        self.sql_factories.clone(),
                        self.sqlx_query_roots.clone(),
                    );
                    visitor.visit_expr(&expression);
                    self.absorb_visitor(visitor);
                }
                CompileInput::Block { source, block } => {
                    let mut visitor = QueryVisitor::new(
                        &path,
                        &source,
                        SqlxNames::default(),
                        self.sql_factories.clone(),
                        self.sqlx_query_roots.clone(),
                    );
                    visitor.visit_block(&block);
                    self.absorb_visitor(visitor);
                }
            }
        }
    }
}

#[derive(Default)]
struct IncludeCollector {
    inputs: Vec<Macro>,
}

impl<'ast> Visit<'ast> for IncludeCollector {
    fn visit_macro(&mut self, mac: &'ast Macro) {
        if macro_path_name(mac).as_deref() == Some("include") {
            self.inputs.push(mac.clone());
        }
        visit::visit_macro(self, mac);
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum SqlxSymbol {
    Crate,
    Query,
    QueryBuilder,
    Other,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum SqlWrapperKind {
    Query,
    Unknown,
    Other,
}

#[derive(Clone, Default)]
struct SqlxScope {
    symbols: HashMap<String, SqlxSymbol>,
    wrappers: HashMap<String, SqlWrapperKind>,
}

#[derive(Clone, Default)]
struct SqlxNames {
    scopes: Vec<SqlxScope>,
}

impl SqlxNames {
    fn with_scope(scope: SqlxScope) -> Self {
        Self {
            scopes: vec![scope],
        }
    }

    fn push_scope(&mut self, scope: SqlxScope) {
        self.scopes.push(scope);
    }

    fn pop_scope(&mut self) {
        self.scopes.pop();
    }

    fn resolve_symbol(&self, name: &str) -> Option<SqlxSymbol> {
        self.scopes
            .iter()
            .rev()
            .find_map(|scope| scope.symbols.get(name).copied())
    }

    fn resolve_wrapper(&self, name: &str) -> Option<SqlWrapperKind> {
        self.scopes
            .iter()
            .rev()
            .find_map(|scope| scope.wrappers.get(name).copied())
    }

    fn shadow(&mut self, name: String) {
        if self.scopes.is_empty() {
            self.push_scope(SqlxScope::default());
        }
        self.scopes
            .last_mut()
            .expect("SQLx name scope")
            .symbols
            .insert(name, SqlxSymbol::Other);
    }

    fn is_crate_name(&self, name: &str) -> bool {
        name == "sqlx" || self.resolve_symbol(name) == Some(SqlxSymbol::Crate)
    }
}

#[derive(Clone, Default)]
struct ScopedFlags {
    scopes: Vec<HashMap<String, bool>>,
}

impl ScopedFlags {
    fn push_scope(&mut self) {
        self.scopes.push(HashMap::new());
    }

    fn pop_scope(&mut self) {
        self.scopes.pop();
    }

    fn declare(&mut self, name: String, value: bool) {
        if self.scopes.is_empty() {
            self.push_scope();
        }
        self.scopes
            .last_mut()
            .expect("scoped flag scope")
            .insert(name, value);
    }

    fn assign(&mut self, name: &str, value: bool) {
        for scope in self.scopes.iter_mut().rev() {
            if scope.contains_key(name) {
                scope.insert(name.to_owned(), value);
                return;
            }
        }
        self.declare(name.to_owned(), value);
    }

    fn resolve(&self, name: &str) -> bool {
        self.scopes
            .iter()
            .rev()
            .find_map(|scope| scope.get(name).copied())
            .unwrap_or(false)
    }
}

#[derive(Clone)]
enum SqlBinding {
    Static(Vec<String>),
    Dynamic,
}

#[derive(Clone, Default)]
struct SqlBindings {
    scopes: Vec<HashMap<String, SqlBinding>>,
}

impl SqlBindings {
    fn push_scope(&mut self) {
        self.scopes.push(HashMap::new());
    }

    fn pop_scope(&mut self) {
        self.scopes.pop();
    }

    fn declare(&mut self, name: String, binding: SqlBinding) {
        if self.scopes.is_empty() {
            self.push_scope();
        }
        self.scopes
            .last_mut()
            .expect("SQL binding scope")
            .insert(name, binding);
    }

    fn assign(&mut self, name: &str, binding: SqlBinding) {
        for scope in self.scopes.iter_mut().rev() {
            if scope.contains_key(name) {
                scope.insert(name.to_owned(), binding);
                return;
            }
        }
        self.declare(name.to_owned(), binding);
    }

    fn contains(&self, name: &str) -> bool {
        self.scopes
            .iter()
            .rev()
            .any(|scope| scope.contains_key(name))
    }

    fn invalidate(&mut self, name: &str) {
        if self.contains(name) {
            self.assign(name, SqlBinding::Dynamic);
        }
    }

    fn resolve(&self, path: &Path, name: &str) -> Result<Vec<String>, String> {
        for scope in self.scopes.iter().rev() {
            match scope.get(name) {
                Some(SqlBinding::Static(values)) => return Ok(values.clone()),
                Some(SqlBinding::Dynamic) => return Err(dynamic_sql_binding(path, name)),
                None => {}
            }
        }
        Err(non_static_sql(path))
    }
}

struct QueryVisitor<'a> {
    path: &'a Path,
    source: &'a str,
    sqlx_names: SqlxNames,
    sql_factories: HashMap<String, Vec<SqlFactory>>,
    sql_values: SqlBindings,
    query_objects: ScopedFlags,
    query_builders: HashMap<String, String>,
    credential_sql: Vec<SqlFinding>,
    unresolved: Vec<String>,
    include_inputs: Vec<PathBuf>,
    sqlx_query_roots: Vec<PathBuf>,
}

impl<'a> QueryVisitor<'a> {
    fn new(
        path: &'a Path,
        source: &'a str,
        sqlx_names: SqlxNames,
        sql_factories: HashMap<String, Vec<SqlFactory>>,
        sqlx_query_roots: Vec<PathBuf>,
    ) -> Self {
        Self {
            path,
            source,
            sqlx_names,
            sql_factories,
            sql_values: SqlBindings::default(),
            query_objects: ScopedFlags::default(),
            query_builders: HashMap::new(),
            credential_sql: Vec::new(),
            unresolved: Vec::new(),
            include_inputs: Vec::new(),
            sqlx_query_roots,
        }
    }

    fn binding_for(&self, expression: &Expr) -> SqlBinding {
        match sql_expression_variants(self.path, expression, &self.sql_values, &self.sql_factories)
        {
            Ok(values) => SqlBinding::Static(values),
            Err(_) => SqlBinding::Dynamic,
        }
    }

    fn invalidate_binding(&mut self, name: &str) {
        self.sql_values.invalidate(name);
        self.query_objects.assign(name, false);
        self.query_builders.remove(name);
    }

    fn invalidate_mutably_borrowed_macro_bindings(&mut self, mac: &Macro) {
        let mut names = BTreeSet::new();
        collect_mutably_borrowed_identifiers(mac.tokens.clone(), &mut names);
        for name in names {
            self.invalidate_binding(&name);
        }
    }

    fn invalidate_bindings_passed_to_unmodeled_macros(&mut self, mac: &Macro) {
        if sqlx_macro_kind(mac, &self.sqlx_names) == Some(SqlxCallKind::Query)
            || macro_path_name(mac).is_some_and(|name| {
                matches!(
                    name.as_str(),
                    "concat" | "format" | "include" | "include_str"
                )
            })
        {
            return;
        }
        let mut identifiers = Vec::new();
        collect_token_identifiers(mac.tokens.clone(), &mut identifiers);
        for name in identifiers.into_iter().collect::<BTreeSet<_>>() {
            if self.sql_values.contains(&name) {
                self.invalidate_binding(&name);
            }
        }
    }

    fn record_sql(&mut self, expression: &Expr) {
        match sql_expression_variants(self.path, expression, &self.sql_values, &self.sql_factories)
        {
            Ok(sql_values) => {
                for sql in sql_values {
                    self.record_sql_text(&sql, expression_line(self.source, expression));
                }
            }
            Err(error) => self.unresolved.push(error),
        }
    }

    fn record_sql_text(&mut self, sql: &str, line: usize) {
        let tables = MANAGED_CREDENTIAL_TABLES
            .iter()
            .copied()
            .filter(|table| sql.contains(table))
            .collect::<BTreeSet<_>>();
        if tables.is_empty() {
            return;
        }
        let finding = SqlFinding {
            path: self.path.to_path_buf(),
            line,
            tables,
        };
        if !self.credential_sql.iter().any(|existing| {
            existing.path == finding.path
                && existing.line == finding.line
                && existing.tables == finding.tables
        }) {
            self.credential_sql.push(finding);
        }
    }

    fn record_literal(&mut self, value: &syn::LitStr) {
        self.record_sql_text(&value.value(), literal_line(self.source, value));
    }

    fn record_sqlx_macro(&mut self, mac: &Macro, input: SqlMacroInput) {
        let parser = Punctuated::<Expr, Token![,]>::parse_terminated;
        let arguments = match parser.parse2(mac.tokens.clone()) {
            Ok(arguments) => arguments,
            Err(error) => {
                self.unresolved.push(format!(
                    "{}: cannot parse SQLx macro input: {error}",
                    self.path.display()
                ));
                return;
            }
        };
        let (index, is_file) = match input {
            SqlMacroInput::Inline(index) => (index, false),
            SqlMacroInput::File(index) => (index, true),
        };
        let Some(expression) = arguments.get(index) else {
            self.unresolved.push(format!(
                "{}: SQLx macro has no SQL input at argument {index}",
                self.path.display()
            ));
            return;
        };
        if !is_file {
            self.record_sql(expression);
            return;
        }
        let Expr::Lit(expression_literal) = expression else {
            self.unresolved.push(format!(
                "{}: SQLx query_file path must be a string literal",
                self.path.display()
            ));
            return;
        };
        let Lit::Str(relative_path) = &expression_literal.lit else {
            self.unresolved.push(format!(
                "{}: SQLx query_file path must be a string literal",
                self.path.display()
            ));
            return;
        };
        match resolve_sqlx_query_file(&self.sqlx_query_roots, relative_path.value().as_str()) {
            Ok(path) => match fs::read_to_string(&path) {
                Ok(sql) => self.record_sql_text(&sql, literal_line(self.source, relative_path)),
                Err(error) => self.unresolved.push(format!(
                    "{}: cannot read SQLx query file {}: {error}",
                    self.path.display(),
                    path.display()
                )),
            },
            Err(error) => self
                .unresolved
                .push(format!("{}: {error}", self.path.display())),
        }
    }
}

impl<'ast> Visit<'ast> for QueryVisitor<'_> {
    fn visit_item_fn(&mut self, function: &'ast syn::ItemFn) {
        let mut parameter_names = BTreeSet::new();
        for argument in &function.sig.inputs {
            if let syn::FnArg::Typed(argument) = argument {
                collect_pattern_identifiers(&argument.pat, &mut parameter_names);
            }
        }
        let mut scope = SqlxScope::default();
        for name in &parameter_names {
            scope.symbols.insert(name.clone(), SqlxSymbol::Other);
        }
        self.sqlx_names.push_scope(scope);
        self.sql_values.push_scope();
        self.query_objects.push_scope();
        for name in parameter_names {
            self.sql_values.declare(name.clone(), SqlBinding::Dynamic);
            self.query_objects.declare(name, false);
        }
        visit::visit_item_fn(self, function);
        self.query_objects.pop_scope();
        self.sql_values.pop_scope();
        self.sqlx_names.pop_scope();
    }

    fn visit_expr_closure(&mut self, closure: &'ast syn::ExprClosure) {
        let mut parameter_names = BTreeSet::new();
        for input in &closure.inputs {
            collect_pattern_identifiers(input, &mut parameter_names);
        }
        let mut scope = SqlxScope::default();
        for name in &parameter_names {
            scope.symbols.insert(name.clone(), SqlxSymbol::Other);
        }
        self.sqlx_names.push_scope(scope);
        self.sql_values.push_scope();
        self.query_objects.push_scope();
        for name in parameter_names {
            self.sql_values.declare(name.clone(), SqlBinding::Dynamic);
            self.query_objects.declare(name, false);
        }
        visit::visit_expr_closure(self, closure);
        self.query_objects.pop_scope();
        self.sql_values.pop_scope();
        self.sqlx_names.pop_scope();
    }

    fn visit_block(&mut self, block: &'ast syn::Block) {
        let sqlx_scope = sqlx_scope_for_statements(
            self.path,
            &block.stmts,
            &self.sqlx_names,
            &mut self.unresolved,
        );
        self.sqlx_names.push_scope(sqlx_scope);
        self.sql_values.push_scope();
        self.query_objects.push_scope();
        visit::visit_block(self, block);
        self.query_objects.pop_scope();
        self.sql_values.pop_scope();
        self.sqlx_names.pop_scope();
    }

    fn visit_local(&mut self, local: &'ast syn::Local) {
        if let (Pat::Ident(binding), Some(init)) = (&local.pat, &local.init) {
            let name = binding.ident.to_string();
            let value = self.binding_for(&init.expr);
            let is_query_object =
                sqlx_query_object_expression(&init.expr, &self.sqlx_names, &self.query_objects);
            if let Some(sql) = query_builder_expression(self.path, &init.expr, &self.sqlx_names) {
                match sql {
                    Ok(sql) => {
                        self.record_sql_text(&sql, expression_line(self.source, &init.expr));
                        self.query_builders.insert(name.clone(), sql);
                    }
                    Err(error) => self.unresolved.push(error),
                }
            } else {
                self.query_builders.remove(&name);
            }
            self.visit_expr(&init.expr);
            if let Some((_, diverge)) = &init.diverge {
                self.visit_expr(diverge);
            }
            self.sql_values.declare(name, value);
            self.query_objects
                .declare(binding.ident.to_string(), is_query_object);
            self.sqlx_names.shadow(binding.ident.to_string());
            return;
        }
        let mut names = BTreeSet::new();
        collect_pattern_identifiers(&local.pat, &mut names);
        if let Some(init) = &local.init {
            self.visit_expr(&init.expr);
            if let Some((_, diverge)) = &init.diverge {
                self.visit_expr(diverge);
            }
        }
        for name in names {
            self.sql_values.declare(name.clone(), SqlBinding::Dynamic);
            self.query_objects.declare(name.clone(), false);
            self.sqlx_names.shadow(name);
        }
        if local.init.is_some() || !matches!(local.pat, Pat::Ident(_)) {
            return;
        }
        visit::visit_local(self, local);
    }

    fn visit_expr_assign(&mut self, assignment: &'ast syn::ExprAssign) {
        if let Some(name) = expression_ident(&assignment.left) {
            let value = self.binding_for(&assignment.right);
            let is_query_object = sqlx_query_object_expression(
                &assignment.right,
                &self.sqlx_names,
                &self.query_objects,
            );
            self.visit_expr(&assignment.right);
            self.visit_expr(&assignment.left);
            self.sql_values.assign(&name, value);
            self.query_objects.assign(&name, is_query_object);
            self.query_builders.remove(&name);
            return;
        }
        visit::visit_expr_assign(self, assignment);
    }

    fn visit_expr_binary(&mut self, binary: &'ast syn::ExprBinary) {
        if is_compound_assignment(&binary.op) {
            let mutated =
                mutable_place_ident(&binary.left).filter(|name| self.sql_values.contains(name));
            self.visit_expr(&binary.left);
            self.visit_expr(&binary.right);
            if let Some(name) = mutated {
                self.invalidate_binding(&name);
            }
            return;
        }
        visit::visit_expr_binary(self, binary);
    }

    fn visit_expr_reference(&mut self, reference: &'ast syn::ExprReference) {
        self.visit_expr(&reference.expr);
        if reference.mutability.is_some() {
            if let Some(name) =
                mutable_place_ident(&reference.expr).filter(|name| self.sql_values.contains(name))
            {
                self.invalidate_binding(&name);
            }
        }
    }

    fn visit_expr_call(&mut self, call: &'ast syn::ExprCall) {
        match sqlx_call_kind(&call.func, &self.sqlx_names) {
            Some(SqlxCallKind::Query) => {
                if let Some(expression) = call.args.first() {
                    self.record_sql(expression);
                } else {
                    self.unresolved.push(format!(
                        "{}: sqlx query call has no SQL input",
                        self.path.display()
                    ));
                }
            }
            Some(SqlxCallKind::Unknown) => self.unresolved.push(format!(
                "{}: unrecognized SQLx execution/query call",
                self.path.display()
            )),
            None => {}
        }
        visit::visit_expr_call(self, call);
    }

    fn visit_expr_method_call(&mut self, call: &'ast syn::ExprMethodCall) {
        let method = call.method.to_string();
        let modeled_query_builder_mutation = matches!(method.as_str(), "push" | "push_unseparated")
            && expression_ident(&call.receiver)
                .is_some_and(|name| self.query_builders.contains_key(&name));
        if is_executor_raw_sql_method(&method)
            && !sqlx_query_object_expression(&call.receiver, &self.sqlx_names, &self.query_objects)
        {
            if let Some(expression) = call.args.first() {
                if !sqlx_query_object_expression(expression, &self.sqlx_names, &self.query_objects)
                {
                    self.record_sql(expression);
                }
            } else {
                self.unresolved.push(format!(
                    "{}: SQLx Executor method `{method}` has no SQL input",
                    self.path.display()
                ));
            }
        }

        if matches!(method.as_str(), "push" | "push_unseparated") {
            if let Some(builder_name) = expression_ident(&call.receiver) {
                if let Some(mut sql) = self.query_builders.get(&builder_name).cloned() {
                    if let Some(expression) = call.args.first() {
                        match static_sql_expression(self.path, expression) {
                            Ok(fragment) => {
                                sql.push_str(&fragment);
                                self.record_sql_text(
                                    &sql,
                                    expression_line(self.source, expression),
                                );
                                self.query_builders.insert(builder_name, sql);
                            }
                            Err(error) => self.unresolved.push(error),
                        }
                    } else {
                        self.unresolved.push(format!(
                            "{}: QueryBuilder push has no SQL input",
                            self.path.display()
                        ));
                    }
                }
            } else if let Some(sql) = query_builder_expression(
                self.path,
                &Expr::MethodCall(call.clone()),
                &self.sqlx_names,
            ) {
                match sql {
                    Ok(sql) => {
                        self.record_sql_text(&sql, expression_line(self.source, &call.receiver))
                    }
                    Err(error) => self.unresolved.push(error),
                }
            }
        }

        let mutated = (!modeled_query_builder_mutation)
            .then(|| mutable_place_ident(&call.receiver))
            .flatten()
            .filter(|name| self.sql_values.contains(name));
        self.visit_expr(&call.receiver);
        for argument in &call.args {
            self.visit_expr(argument);
        }
        if let Some(name) = mutated {
            self.invalidate_binding(&name);
        }
    }

    fn visit_macro(&mut self, mac: &'ast Macro) {
        if macro_path_name(mac).as_deref() == Some("include") {
            match compile_input_path(self.path, mac) {
                Ok(path) => self.include_inputs.push(path),
                Err(error) => self.unresolved.push(error),
            }
        } else if let Some(input) = sqlx_query_macro_input(mac, &self.sqlx_names) {
            self.record_sqlx_macro(mac, input);
        } else if sqlx_macro_kind(mac, &self.sqlx_names) == Some(SqlxCallKind::Query) {
            self.unresolved.push(format!(
                "{}: unrecognized SQLx execution/query macro",
                self.path.display()
            ));
        } else if macro_path_name(mac).is_some_and(|name| {
            self.sqlx_names.resolve_wrapper(&name) == Some(SqlWrapperKind::Query)
        }) {
            let parser = Punctuated::<Expr, Token![,]>::parse_terminated;
            match parser.parse2(mac.tokens.clone()) {
                Ok(arguments) => {
                    if let Some(expression) = arguments.first() {
                        self.record_sql(expression);
                    } else {
                        self.unresolved.push(format!(
                            "{}: SQL macro has no SQL input",
                            self.path.display()
                        ));
                    }
                }
                Err(error) => self.unresolved.push(format!(
                    "{}: cannot parse SQL macro input: {error}",
                    self.path.display()
                )),
            }
        } else if macro_path_name(mac).is_some_and(|name| {
            self.sqlx_names.resolve_wrapper(&name) == Some(SqlWrapperKind::Unknown)
        }) {
            self.unresolved.push(format!(
                "{}: unresolved SQL wrapper macro `{}`",
                self.path.display(),
                macro_path_name(mac).unwrap_or_default()
            ));
        } else if sqlx_macro_kind(mac, &self.sqlx_names) == Some(SqlxCallKind::Unknown) {
            self.unresolved.push(format!(
                "{}: unrecognized SQLx execution/query macro",
                self.path.display()
            ));
        }
        self.invalidate_mutably_borrowed_macro_bindings(mac);
        self.invalidate_bindings_passed_to_unmodeled_macros(mac);
        visit::visit_macro(self, mac);
    }

    fn visit_lit_str(&mut self, literal: &'ast syn::LitStr) {
        self.record_literal(literal);
        visit::visit_lit_str(self, literal);
    }
}

fn sql_factory(function: &syn::ItemFn) -> Result<Option<SqlFactory>, String> {
    let syn::ReturnType::Type(_, return_type) = &function.sig.output else {
        return Ok(None);
    };
    if !is_string_return_type(return_type) {
        return Ok(None);
    }
    let parameters = function
        .sig
        .inputs
        .iter()
        .map(|argument| match argument {
            syn::FnArg::Typed(argument) => match argument.pat.as_ref() {
                Pat::Ident(binding) => Ok(binding.ident.to_string()),
                _ => Err(format!(
                    "static SQL factory {} parameters must be identifiers",
                    function.sig.ident
                )),
            },
            syn::FnArg::Receiver(_) => Err(format!(
                "static SQL factory {} may not have a receiver",
                function.sig.ident
            )),
        })
        .collect::<Result<Vec<_>, _>>()?;
    Ok(Some(SqlFactory {
        parameters,
        body: (*function.block).clone(),
    }))
}

fn is_string_return_type(return_type: &syn::Type) -> bool {
    match return_type {
        syn::Type::Path(path) => path
            .path
            .segments
            .last()
            .is_some_and(|segment| segment.ident == "String"),
        syn::Type::Reference(reference) => matches!(
            reference.elem.as_ref(),
            syn::Type::Path(path) if path.path.is_ident("str")
        ),
        _ => false,
    }
}

fn sql_expression_variants(
    path: &Path,
    expression: &Expr,
    values: &SqlBindings,
    factories: &HashMap<String, Vec<SqlFactory>>,
) -> Result<Vec<String>, String> {
    sql_expression_variants_inner(path, expression, values, factories, &mut Vec::new())
}

fn sql_expression_variants_inner(
    path: &Path,
    expression: &Expr,
    values: &SqlBindings,
    factories: &HashMap<String, Vec<SqlFactory>>,
    factory_stack: &mut Vec<String>,
) -> Result<Vec<String>, String> {
    match expression {
        Expr::Path(expression_path) if expression_path.path.segments.len() == 1 => {
            let name = expression_path.path.segments[0].ident.to_string();
            values.resolve(path, &name)
        }
        Expr::Lit(literal) => match &literal.lit {
            Lit::Str(value) => Ok(vec![value.value()]),
            _ => Err(non_static_sql(path)),
        },
        Expr::Reference(reference) => {
            sql_expression_variants_inner(path, &reference.expr, values, factories, factory_stack)
        }
        Expr::Group(group) => {
            sql_expression_variants_inner(path, &group.expr, values, factories, factory_stack)
        }
        Expr::Paren(paren) => {
            sql_expression_variants_inner(path, &paren.expr, values, factories, factory_stack)
        }
        Expr::Block(block) => {
            block_sql_variants(path, &block.block, values, factories, factory_stack)
        }
        Expr::Match(expression_match) => {
            let mut variants = Vec::new();
            for arm in &expression_match.arms {
                variants.extend(sql_expression_variants_inner(
                    path,
                    &arm.body,
                    values,
                    factories,
                    factory_stack,
                )?);
            }
            Ok(deduplicate_variants(variants))
        }
        Expr::If(expression_if) => {
            let mut variants = block_sql_variants(
                path,
                &expression_if.then_branch,
                values,
                factories,
                factory_stack,
            )?;
            let Some((_, else_branch)) = &expression_if.else_branch else {
                return Err(non_static_sql(path));
            };
            variants.extend(sql_expression_variants_inner(
                path,
                else_branch,
                values,
                factories,
                factory_stack,
            )?);
            Ok(deduplicate_variants(variants))
        }
        Expr::Binary(binary) if matches!(binary.op, syn::BinOp::Add(_)) => concatenate_variants(
            sql_expression_variants_inner(path, &binary.left, values, factories, factory_stack)?,
            sql_expression_variants_inner(path, &binary.right, values, factories, factory_stack)?,
        ),
        Expr::Macro(expression_macro)
            if macro_path_name(&expression_macro.mac).as_deref() == Some("concat") =>
        {
            let parser = Punctuated::<Expr, Token![,]>::parse_terminated;
            let arguments = parser
                .parse2(expression_macro.mac.tokens.clone())
                .map_err(|_| non_static_sql(path))?;
            let mut variants = vec![String::new()];
            for argument in arguments {
                variants = concatenate_variants(
                    variants,
                    sql_expression_variants_inner(
                        path,
                        &argument,
                        values,
                        factories,
                        factory_stack,
                    )?,
                )?;
            }
            Ok(variants)
        }
        Expr::Macro(expression_macro)
            if macro_path_name(&expression_macro.mac).as_deref() == Some("format") =>
        {
            format_sql_variants(
                path,
                &expression_macro.mac,
                values,
                factories,
                factory_stack,
            )
        }
        Expr::Macro(expression_macro)
            if macro_path_name(&expression_macro.mac).as_deref() == Some("include_str") =>
        {
            let include_path = compile_input_path(path, &expression_macro.mac)?;
            fs::read_to_string(&include_path)
                .map(|sql| vec![sql])
                .map_err(|_| non_static_sql(path))
        }
        Expr::Call(call) => {
            let Expr::Path(function) = call.func.as_ref() else {
                return Err(non_static_sql(path));
            };
            let Some(name) = function
                .path
                .segments
                .last()
                .map(|segment| segment.ident.to_string())
            else {
                return Err(non_static_sql(path));
            };
            let Some(candidates) = factories.get(&name) else {
                return Err(non_static_sql(path));
            };
            let [factory] = candidates.as_slice() else {
                return Err(non_static_sql(path));
            };
            if call.args.len() != factory.parameters.len()
                || factory_stack.len() >= 32
                || factory_stack.iter().any(|active| active == &name)
            {
                return Err(non_static_sql(path));
            }
            let mut factory_values = SqlBindings::default();
            factory_values.push_scope();
            for (parameter, argument) in factory.parameters.iter().zip(&call.args) {
                let binding = match sql_expression_variants_inner(
                    path,
                    argument,
                    values,
                    factories,
                    factory_stack,
                ) {
                    Ok(variants) => SqlBinding::Static(variants),
                    Err(_) => SqlBinding::Dynamic,
                };
                factory_values.declare(parameter.clone(), binding);
            }
            factory_stack.push(name);
            let result = block_sql_variants(
                path,
                &factory.body,
                &factory_values,
                factories,
                factory_stack,
            );
            factory_stack.pop();
            result
        }
        Expr::Return(expression_return) => expression_return
            .expr
            .as_deref()
            .ok_or_else(|| non_static_sql(path))
            .and_then(|returned| {
                sql_expression_variants_inner(path, returned, values, factories, factory_stack)
            }),
        _ => Err(non_static_sql(path)),
    }
}

fn block_sql_variants(
    path: &Path,
    block: &syn::Block,
    values: &SqlBindings,
    factories: &HashMap<String, Vec<SqlFactory>>,
    factory_stack: &mut Vec<String>,
) -> Result<Vec<String>, String> {
    let mut block_values = values.clone();
    block_values.push_scope();
    for (index, statement) in block.stmts.iter().enumerate() {
        match statement {
            syn::Stmt::Local(local) => {
                let Some(init) = &local.init else {
                    continue;
                };
                invalidate_expression_mutations(&init.expr, &mut block_values);
                let Pat::Ident(binding) = &local.pat else {
                    continue;
                };
                let value = match sql_expression_variants_inner(
                    path,
                    &init.expr,
                    &block_values,
                    factories,
                    factory_stack,
                ) {
                    Ok(variants) => SqlBinding::Static(variants),
                    Err(_) => SqlBinding::Dynamic,
                };
                block_values.declare(binding.ident.to_string(), value);
            }
            syn::Stmt::Expr(Expr::Assign(assignment), _) => {
                let Some(name) = expression_ident(&assignment.left) else {
                    return Err(non_static_sql(path));
                };
                invalidate_expression_mutations(&assignment.right, &mut block_values);
                let value = match sql_expression_variants_inner(
                    path,
                    &assignment.right,
                    &block_values,
                    factories,
                    factory_stack,
                ) {
                    Ok(variants) => SqlBinding::Static(variants),
                    Err(_) => SqlBinding::Dynamic,
                };
                block_values.assign(&name, value);
            }
            syn::Stmt::Expr(Expr::Binary(binary), _) if is_compound_assignment(&binary.op) => {
                if !invalidate_expression_mutations(
                    &Expr::Binary(binary.clone()),
                    &mut block_values,
                ) {
                    return Err(non_static_sql(path));
                }
            }
            syn::Stmt::Expr(Expr::Return(expression_return), _) => {
                let returned = expression_return
                    .expr
                    .as_deref()
                    .ok_or_else(|| non_static_sql(path))?;
                invalidate_expression_mutations(returned, &mut block_values);
                return sql_expression_variants_inner(
                    path,
                    returned,
                    &block_values,
                    factories,
                    factory_stack,
                );
            }
            syn::Stmt::Expr(expression, None) if index + 1 == block.stmts.len() => {
                invalidate_expression_mutations(expression, &mut block_values);
                return sql_expression_variants_inner(
                    path,
                    expression,
                    &block_values,
                    factories,
                    factory_stack,
                );
            }
            syn::Stmt::Expr(expression, _) => {
                if !invalidate_expression_mutations(expression, &mut block_values) {
                    return Err(non_static_sql(path));
                }
            }
            syn::Stmt::Macro(statement_macro) => {
                let mut names = BTreeSet::new();
                collect_mutably_borrowed_identifiers(
                    statement_macro.mac.tokens.clone(),
                    &mut names,
                );
                let mut invalidated = false;
                for name in names {
                    if block_values.contains(&name) {
                        block_values.invalidate(&name);
                        invalidated = true;
                    }
                }
                if !invalidated {
                    return Err(non_static_sql(path));
                }
            }
            syn::Stmt::Item(_) => return Err(non_static_sql(path)),
        }
    }
    Err(non_static_sql(path))
}

fn format_sql_variants(
    path: &Path,
    mac: &Macro,
    values: &SqlBindings,
    factories: &HashMap<String, Vec<SqlFactory>>,
    factory_stack: &mut Vec<String>,
) -> Result<Vec<String>, String> {
    let parser = Punctuated::<Expr, Token![,]>::parse_terminated;
    let arguments = parser
        .parse2(mac.tokens.clone())
        .map_err(|_| non_static_sql(path))?;
    let mut arguments = arguments.into_iter();
    let Some(template_expression) = arguments.next() else {
        return Err(non_static_sql(path));
    };
    let templates = sql_expression_variants_inner(
        path,
        &template_expression,
        values,
        factories,
        factory_stack,
    )?;
    let mut positional = Vec::new();
    let mut named = HashMap::new();
    for argument in arguments {
        if let Expr::Assign(assignment) = &argument {
            let Some(name) = expression_ident(&assignment.left) else {
                return Err(non_static_sql(path));
            };
            if named
                .insert(
                    name,
                    sql_expression_variants_inner(
                        path,
                        &assignment.right,
                        values,
                        factories,
                        factory_stack,
                    )?,
                )
                .is_some()
            {
                return Err(non_static_sql(path));
            }
        } else {
            positional.push(sql_expression_variants_inner(
                path,
                &argument,
                values,
                factories,
                factory_stack,
            )?);
        }
    }
    let mut rendered = Vec::new();
    for template in templates {
        rendered.extend(render_format_template(
            path,
            &template,
            &positional,
            &named,
            values,
        )?);
    }
    Ok(deduplicate_variants(rendered))
}

fn render_format_template(
    path: &Path,
    template: &str,
    positional: &[Vec<String>],
    named: &HashMap<String, Vec<String>>,
    captured: &SqlBindings,
) -> Result<Vec<String>, String> {
    let bytes = template.as_bytes();
    let mut rendered = vec![String::new()];
    let mut literal_start = 0;
    let mut index = 0;
    let mut next_positional = 0;
    while index < bytes.len() {
        match bytes[index] {
            b'{' if bytes.get(index + 1) == Some(&b'{') => {
                append_literal(&mut rendered, &template[literal_start..index]);
                append_literal(&mut rendered, "{");
                index += 2;
                literal_start = index;
            }
            b'{' => {
                append_literal(&mut rendered, &template[literal_start..index]);
                let field_start = index + 1;
                let Some(relative_end) = bytes[field_start..].iter().position(|byte| *byte == b'}')
                else {
                    return Err(non_static_sql(path));
                };
                let field_end = field_start + relative_end;
                let field = &template[field_start..field_end];
                if field.contains([':', '!']) {
                    return Err(non_static_sql(path));
                }
                let variants = if field.is_empty() {
                    let variants = positional
                        .get(next_positional)
                        .ok_or_else(|| non_static_sql(path))?;
                    next_positional += 1;
                    variants.clone()
                } else if let Ok(position) = field.parse::<usize>() {
                    positional
                        .get(position)
                        .ok_or_else(|| non_static_sql(path))?
                        .clone()
                } else if field
                    .chars()
                    .all(|character| character == '_' || character.is_ascii_alphanumeric())
                {
                    match named.get(field) {
                        Some(variants) => variants.clone(),
                        None => captured.resolve(path, field)?,
                    }
                } else {
                    return Err(non_static_sql(path));
                };
                rendered = concatenate_variants(rendered, variants)?;
                index = field_end + 1;
                literal_start = index;
            }
            b'}' if bytes.get(index + 1) == Some(&b'}') => {
                append_literal(&mut rendered, &template[literal_start..index]);
                append_literal(&mut rendered, "}");
                index += 2;
                literal_start = index;
            }
            b'}' => return Err(non_static_sql(path)),
            _ => index += 1,
        }
    }
    append_literal(&mut rendered, &template[literal_start..]);
    Ok(deduplicate_variants(rendered))
}

fn append_literal(variants: &mut [String], literal: &str) {
    for variant in variants {
        variant.push_str(literal);
    }
}

fn concatenate_variants(left: Vec<String>, right: Vec<String>) -> Result<Vec<String>, String> {
    let size = left
        .len()
        .checked_mul(right.len())
        .filter(|size| *size <= 4096)
        .ok_or_else(|| "static SQL variant set is not inventory-safe".to_string())?;
    let mut combined = Vec::with_capacity(size);
    for prefix in left {
        for suffix in &right {
            combined.push(format!("{prefix}{suffix}"));
        }
    }
    Ok(deduplicate_variants(combined))
}

fn deduplicate_variants(variants: Vec<String>) -> Vec<String> {
    variants
        .into_iter()
        .collect::<BTreeSet<_>>()
        .into_iter()
        .collect()
}

fn static_sql_expression(path: &Path, expression: &Expr) -> Result<String, String> {
    match expression {
        Expr::Lit(literal) => match &literal.lit {
            Lit::Str(value) => Ok(value.value()),
            _ => Err(non_static_sql(path)),
        },
        Expr::Group(group) => static_sql_expression(path, &group.expr),
        Expr::Paren(paren) => static_sql_expression(path, &paren.expr),
        Expr::Reference(reference) => static_sql_expression(path, &reference.expr),
        Expr::Binary(binary) if matches!(binary.op, syn::BinOp::Add(_)) => Ok(format!(
            "{}{}",
            static_sql_expression(path, &binary.left)?,
            static_sql_expression(path, &binary.right)?
        )),
        Expr::Macro(expression_macro)
            if macro_path_name(&expression_macro.mac).as_deref() == Some("include_str") =>
        {
            let include_path = compile_input_path(path, &expression_macro.mac)?;
            fs::read_to_string(&include_path).map_err(|error| {
                format!(
                    "cannot read SQL include_str compile input {}: {error}",
                    include_path.display()
                )
            })
        }
        Expr::Macro(expression_macro)
            if macro_path_name(&expression_macro.mac).as_deref() == Some("concat") =>
        {
            let parser = Punctuated::<Expr, Token![,]>::parse_terminated;
            let arguments =
                parser
                    .parse2(expression_macro.mac.tokens.clone())
                    .map_err(|error| {
                        format!(
                            "{}: cannot parse concat! SQL input: {error}",
                            path.display()
                        )
                    })?;
            let mut sql = String::new();
            for argument in arguments {
                sql.push_str(&static_sql_expression(path, &argument)?);
            }
            Ok(sql)
        }
        _ => Err(non_static_sql(path)),
    }
}

fn query_builder_expression(
    path: &Path,
    expression: &Expr,
    names: &SqlxNames,
) -> Option<Result<String, String>> {
    match expression {
        Expr::Call(call) if is_query_builder_new(&call.func, names) => Some(
            call.args
                .first()
                .ok_or_else(|| format!("{}: QueryBuilder::new has no SQL input", path.display()))
                .and_then(|expression| static_sql_expression(path, expression)),
        ),
        Expr::MethodCall(call)
            if matches!(
                call.method.to_string().as_str(),
                "push" | "push_unseparated"
            ) =>
        {
            let base = query_builder_expression(path, &call.receiver, names)?;
            Some(base.and_then(|mut sql| {
                let expression = call.args.first().ok_or_else(|| {
                    format!("{}: QueryBuilder push has no SQL input", path.display())
                })?;
                sql.push_str(&static_sql_expression(path, expression)?);
                Ok(sql)
            }))
        }
        Expr::Group(group) => query_builder_expression(path, &group.expr, names),
        Expr::Paren(paren) => query_builder_expression(path, &paren.expr, names),
        _ => None,
    }
}

fn non_static_sql(path: &Path) -> String {
    format!(
        "{}: non-static SQL input is not inventory-safe",
        path.display()
    )
}

fn dynamic_sql_binding(path: &Path, name: &str) -> String {
    format!(
        "{}: non-static SQL input from dynamic SQL binding `{name}` is not inventory-safe",
        path.display()
    )
}

fn resolve_module_path(
    source_path: &Path,
    module_dir: &Path,
    module: &syn::ItemMod,
) -> Result<PathBuf, String> {
    if let Some(path) = explicit_module_path(source_path, &module.attrs)? {
        return Ok(path);
    }
    let name = module.ident.to_string();
    let candidates = [
        module_dir.join(format!("{name}.rs")),
        module_dir.join(&name).join("mod.rs"),
    ];
    let existing = candidates
        .into_iter()
        .filter(|candidate| candidate.is_file())
        .collect::<Vec<_>>();
    match existing.as_slice() {
        [path] => Ok(path.clone()),
        [] => Err(format!(
            "{}: cannot resolve module {}",
            source_path.display(),
            name
        )),
        _ => Err(format!(
            "{}: module {} resolves ambiguously",
            source_path.display(),
            name
        )),
    }
}

fn explicit_module_path(
    source_path: &Path,
    attributes: &[Attribute],
) -> Result<Option<PathBuf>, String> {
    for attribute in attributes {
        if attribute.path().is_ident("cfg_attr") && tokens_contain_ident(&attribute.meta, "path") {
            return Err(format!(
                "{}: cfg_attr(path = ...) cannot be resolved fail-open",
                source_path.display()
            ));
        }
    }
    let paths = attributes
        .iter()
        .filter(|attribute| attribute.path().is_ident("path"))
        .collect::<Vec<_>>();
    match paths.as_slice() {
        [] => Ok(None),
        [attribute] => match &attribute.meta {
            Meta::NameValue(name_value) => match &name_value.value {
                Expr::Lit(literal) => match &literal.lit {
                    Lit::Str(path) => Ok(Some(
                        source_path
                            .parent()
                            .unwrap_or_else(|| Path::new("."))
                            .join(path.value()),
                    )),
                    _ => Err(format!(
                        "{}: #[path] must use a string literal",
                        source_path.display()
                    )),
                },
                _ => Err(format!(
                    "{}: #[path] must use a static literal",
                    source_path.display()
                )),
            },
            _ => Err(format!(
                "{}: malformed #[path] attribute",
                source_path.display()
            )),
        },
        _ => Err(format!(
            "{}: duplicate #[path] attributes",
            source_path.display()
        )),
    }
}

#[derive(Clone)]
struct UseBinding {
    path: Vec<String>,
    local: Option<String>,
    glob: bool,
}

fn sqlx_scope_for_items(
    path: &Path,
    items: &[Item],
    outer: &SqlxNames,
    unresolved: &mut Vec<String>,
) -> SqlxScope {
    let uses = items
        .iter()
        .filter(|item| !is_test_only(item_attrs(item)))
        .filter_map(|item| match item {
            Item::Use(item_use) => Some(&item_use.tree),
            _ => None,
        });
    let macros = items
        .iter()
        .filter(|item| !is_test_only(item_attrs(item)))
        .filter_map(|item| match item {
            Item::Macro(item_macro) if item_macro.mac.path.is_ident("macro_rules") => item_macro
                .ident
                .as_ref()
                .map(|ident| (ident.to_string(), item_macro.mac.tokens.clone())),
            _ => None,
        });
    build_sqlx_scope(path, uses, macros, outer, unresolved)
}

fn sqlx_scope_for_statements(
    path: &Path,
    statements: &[syn::Stmt],
    outer: &SqlxNames,
    unresolved: &mut Vec<String>,
) -> SqlxScope {
    let uses = statements.iter().filter_map(|statement| match statement {
        syn::Stmt::Item(Item::Use(item_use)) => Some(&item_use.tree),
        _ => None,
    });
    let macros = statements.iter().filter_map(|statement| match statement {
        syn::Stmt::Item(Item::Macro(item_macro)) if item_macro.mac.path.is_ident("macro_rules") => {
            item_macro
                .ident
                .as_ref()
                .map(|ident| (ident.to_string(), item_macro.mac.tokens.clone()))
        }
        _ => None,
    });
    build_sqlx_scope(path, uses, macros, outer, unresolved)
}

fn build_sqlx_scope<'a>(
    path: &Path,
    uses: impl Iterator<Item = &'a UseTree>,
    macros: impl Iterator<Item = (String, TokenStream)>,
    outer: &SqlxNames,
    unresolved: &mut Vec<String>,
) -> SqlxScope {
    let mut bindings = Vec::new();
    for tree in uses {
        flatten_use_tree(tree, &mut Vec::new(), &mut bindings);
    }

    let mut scope = SqlxScope::default();
    for binding in &bindings {
        if let Some(local) = &binding.local {
            scope.symbols.insert(local.clone(), SqlxSymbol::Other);
        }
    }
    for binding in &bindings {
        if binding.path.as_slice() == ["sqlx"] {
            if let Some(local) = &binding.local {
                scope.symbols.insert(local.clone(), SqlxSymbol::Crate);
            }
        }
    }

    let mut names = outer.clone();
    names.push_scope(scope.clone());
    for binding in &bindings {
        let root_is_sqlx = binding
            .path
            .first()
            .is_some_and(|root| names.is_crate_name(root));
        if binding.glob {
            if root_is_sqlx {
                unresolved.push(format!(
                    "{}: sqlx glob import is not inventory-safe",
                    path.display()
                ));
            }
            continue;
        }
        let Some(local) = &binding.local else {
            continue;
        };
        let symbol = if binding.path.len() == 1 && root_is_sqlx {
            SqlxSymbol::Crate
        } else if root_is_sqlx
            && binding
                .path
                .last()
                .is_some_and(|name| is_sqlx_query_name(name))
        {
            SqlxSymbol::Query
        } else if root_is_sqlx
            && binding
                .path
                .last()
                .is_some_and(|name| name == "QueryBuilder")
        {
            SqlxSymbol::QueryBuilder
        } else {
            if root_is_sqlx
                && binding
                    .path
                    .last()
                    .is_some_and(|name| is_potential_sqlx_execution_name(name))
            {
                unresolved.push(format!(
                    "{}: unrecognized SQLx execution/query import `{}`",
                    path.display(),
                    binding.path.join("::")
                ));
            }
            SqlxSymbol::Other
        };
        scope.symbols.insert(local.clone(), symbol);
    }

    names.pop_scope();
    names.push_scope(scope.clone());
    for (name, tokens) in macros {
        let kind = macro_body_sqlx_kind(&tokens, &names).unwrap_or(SqlWrapperKind::Other);
        scope.wrappers.insert(name, kind);
    }
    scope
}

fn flatten_use_tree(tree: &UseTree, prefix: &mut Vec<String>, bindings: &mut Vec<UseBinding>) {
    match tree {
        UseTree::Path(item) => {
            prefix.push(item.ident.to_string());
            flatten_use_tree(&item.tree, prefix, bindings);
            prefix.pop();
        }
        UseTree::Name(item) => {
            let mut full = prefix.clone();
            let name = item.ident.to_string();
            if name != "self" {
                full.push(name.clone());
            }
            bindings.push(UseBinding {
                path: full,
                local: Some(if name == "self" {
                    prefix.last().cloned().unwrap_or(name)
                } else {
                    name
                }),
                glob: false,
            });
        }
        UseTree::Rename(item) => {
            let mut full = prefix.clone();
            if item.ident != "self" {
                full.push(item.ident.to_string());
            }
            bindings.push(UseBinding {
                path: full,
                local: Some(item.rename.to_string()),
                glob: false,
            });
        }
        UseTree::Group(group) => {
            for item in &group.items {
                flatten_use_tree(item, prefix, bindings);
            }
        }
        UseTree::Glob(_) => bindings.push(UseBinding {
            path: prefix.clone(),
            local: None,
            glob: true,
        }),
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum SqlxCallKind {
    Query,
    Unknown,
}

fn sqlx_call_kind(expression: &Expr, names: &SqlxNames) -> Option<SqlxCallKind> {
    let Expr::Path(path) = expression else {
        return None;
    };
    sqlx_path_call_kind(&path_segments(&path.path), names)
}

fn sqlx_path_call_kind(segments: &[String], names: &SqlxNames) -> Option<SqlxCallKind> {
    if segments.len() == 1 {
        return (names.resolve_symbol(&segments[0]) == Some(SqlxSymbol::Query))
            .then_some(SqlxCallKind::Query);
    }
    let root = segments.first()?;
    if !names.is_crate_name(root) {
        return None;
    }
    let name = segments.last()?;
    if is_sqlx_query_name(name) {
        Some(SqlxCallKind::Query)
    } else if is_potential_sqlx_execution_name(name) {
        Some(SqlxCallKind::Unknown)
    } else {
        None
    }
}

fn path_segments(path: &syn::Path) -> Vec<String> {
    path.segments
        .iter()
        .map(|segment| segment.ident.to_string())
        .collect()
}

fn is_sqlx_query_name(name: &str) -> bool {
    matches!(
        name,
        "query"
            | "query_as"
            | "query_scalar"
            | "query_with"
            | "query_as_with"
            | "query_scalar_with"
            | "raw_sql"
    )
}

#[derive(Clone, Copy)]
enum SqlMacroInput {
    Inline(usize),
    File(usize),
}

fn sqlx_query_macro_input(mac: &Macro, names: &SqlxNames) -> Option<SqlMacroInput> {
    if sqlx_macro_kind(mac, names) != Some(SqlxCallKind::Query) {
        return None;
    }
    let name = mac.path.segments.last()?.ident.to_string();
    match name.as_str() {
        "query" | "query_scalar" | "query_unchecked" => Some(SqlMacroInput::Inline(0)),
        "query_as" | "query_as_unchecked" => Some(SqlMacroInput::Inline(1)),
        "query_file" | "query_file_scalar" => Some(SqlMacroInput::File(0)),
        "query_file_as" | "query_file_as_unchecked" => Some(SqlMacroInput::File(1)),
        _ => None,
    }
}

fn sqlx_macro_kind(mac: &Macro, names: &SqlxNames) -> Option<SqlxCallKind> {
    let segments = path_segments(&mac.path);
    let name = segments.last()?;
    if segments.len() == 1 {
        return (names.resolve_symbol(&segments[0]) == Some(SqlxSymbol::Query))
            .then_some(SqlxCallKind::Query);
    }
    let is_sqlx_path = segments
        .first()
        .is_some_and(|root| names.is_crate_name(root));
    if !is_sqlx_path {
        return None;
    }
    if is_supported_sqlx_query_macro(name) {
        Some(SqlxCallKind::Query)
    } else if is_potential_sqlx_execution_name(name) {
        Some(SqlxCallKind::Unknown)
    } else {
        None
    }
}

fn is_potential_sqlx_execution_name(name: &str) -> bool {
    name.starts_with("query") || name.starts_with("execute") || name.contains("raw_sql")
}

fn is_supported_sqlx_query_macro(name: &str) -> bool {
    matches!(
        name,
        "query"
            | "query_as"
            | "query_scalar"
            | "query_unchecked"
            | "query_as_unchecked"
            | "query_file"
            | "query_file_as"
            | "query_file_scalar"
            | "query_file_as_unchecked"
    )
}

fn is_query_builder_new(expression: &Expr, names: &SqlxNames) -> bool {
    let Expr::Path(path) = expression else {
        return false;
    };
    let segments = path_segments(&path.path);
    (segments.len() >= 3
        && names.is_crate_name(&segments[0])
        && segments[segments.len() - 2] == "QueryBuilder"
        && segments.last().is_some_and(|segment| segment == "new"))
        || (segments.len() == 2
            && names.resolve_symbol(&segments[0]) == Some(SqlxSymbol::QueryBuilder)
            && segments[1] == "new")
}

fn sqlx_query_object_expression(
    expression: &Expr,
    names: &SqlxNames,
    query_objects: &ScopedFlags,
) -> bool {
    match expression {
        Expr::Call(call) => sqlx_call_kind(&call.func, names) == Some(SqlxCallKind::Query),
        Expr::Macro(expression_macro) => {
            sqlx_macro_kind(&expression_macro.mac, names) == Some(SqlxCallKind::Query)
        }
        Expr::MethodCall(call) => {
            sqlx_query_object_expression(&call.receiver, names, query_objects)
        }
        Expr::Path(path) if path.path.segments.len() == 1 => path
            .path
            .segments
            .first()
            .is_some_and(|segment| query_objects.resolve(&segment.ident.to_string())),
        Expr::Group(group) => sqlx_query_object_expression(&group.expr, names, query_objects),
        Expr::Paren(paren) => sqlx_query_object_expression(&paren.expr, names, query_objects),
        Expr::Reference(reference) => {
            sqlx_query_object_expression(&reference.expr, names, query_objects)
        }
        Expr::Try(expression_try) => {
            sqlx_query_object_expression(&expression_try.expr, names, query_objects)
        }
        Expr::Await(expression_await) => {
            sqlx_query_object_expression(&expression_await.base, names, query_objects)
        }
        _ => false,
    }
}

fn is_executor_raw_sql_method(name: &str) -> bool {
    matches!(
        name,
        "execute"
            | "execute_many"
            | "fetch"
            | "fetch_many"
            | "fetch_all"
            | "fetch_one"
            | "fetch_optional"
            | "prepare"
            | "prepare_with"
    )
}

fn is_compound_assignment(operator: &syn::BinOp) -> bool {
    matches!(
        operator,
        syn::BinOp::AddAssign(_)
            | syn::BinOp::SubAssign(_)
            | syn::BinOp::MulAssign(_)
            | syn::BinOp::DivAssign(_)
            | syn::BinOp::RemAssign(_)
            | syn::BinOp::BitXorAssign(_)
            | syn::BinOp::BitAndAssign(_)
            | syn::BinOp::BitOrAssign(_)
            | syn::BinOp::ShlAssign(_)
            | syn::BinOp::ShrAssign(_)
    )
}

fn mutable_place_ident(expression: &Expr) -> Option<String> {
    match expression {
        Expr::Path(_) => expression_ident(expression),
        Expr::Field(field) => mutable_place_ident(&field.base),
        Expr::Index(index) => mutable_place_ident(&index.expr),
        Expr::Group(group) => mutable_place_ident(&group.expr),
        Expr::Paren(paren) => mutable_place_ident(&paren.expr),
        Expr::Unary(unary) => mutable_place_ident(&unary.expr),
        _ => None,
    }
}

fn collect_pattern_identifiers(pattern: &Pat, names: &mut BTreeSet<String>) {
    struct PatternCollector<'a> {
        names: &'a mut BTreeSet<String>,
    }

    impl<'ast> Visit<'ast> for PatternCollector<'_> {
        fn visit_pat_ident(&mut self, pattern: &'ast syn::PatIdent) {
            self.names.insert(pattern.ident.to_string());
            visit::visit_pat_ident(self, pattern);
        }
    }

    PatternCollector { names }.visit_pat(pattern);
}

#[derive(Default)]
struct MutationCollector {
    names: BTreeSet<String>,
}

impl<'ast> Visit<'ast> for MutationCollector {
    fn visit_expr_macro(&mut self, expression_macro: &'ast syn::ExprMacro) {
        if !macro_path_name(&expression_macro.mac).is_some_and(|name| {
            matches!(
                name.as_str(),
                "concat" | "format" | "include" | "include_str"
            )
        }) {
            let mut identifiers = Vec::new();
            collect_token_identifiers(expression_macro.mac.tokens.clone(), &mut identifiers);
            self.names.extend(identifiers);
        }
        visit::visit_expr_macro(self, expression_macro);
    }

    fn visit_expr_assign(&mut self, assignment: &'ast syn::ExprAssign) {
        if let Some(name) = mutable_place_ident(&assignment.left) {
            self.names.insert(name);
        }
        visit::visit_expr_assign(self, assignment);
    }

    fn visit_expr_binary(&mut self, binary: &'ast syn::ExprBinary) {
        if is_compound_assignment(&binary.op) {
            if let Some(name) = mutable_place_ident(&binary.left) {
                self.names.insert(name);
            }
        }
        visit::visit_expr_binary(self, binary);
    }

    fn visit_expr_method_call(&mut self, call: &'ast syn::ExprMethodCall) {
        if let Some(name) = mutable_place_ident(&call.receiver) {
            self.names.insert(name);
        }
        visit::visit_expr_method_call(self, call);
    }

    fn visit_expr_reference(&mut self, reference: &'ast syn::ExprReference) {
        if reference.mutability.is_some() {
            if let Some(name) = mutable_place_ident(&reference.expr) {
                self.names.insert(name);
            }
        }
        visit::visit_expr_reference(self, reference);
    }
}

fn invalidate_expression_mutations(expression: &Expr, values: &mut SqlBindings) -> bool {
    let mut collector = MutationCollector::default();
    collector.visit_expr(expression);
    let mut invalidated = false;
    for name in collector.names {
        if values.contains(&name) {
            values.invalidate(&name);
            invalidated = true;
        }
    }
    invalidated
}

fn expression_ident(expression: &Expr) -> Option<String> {
    let Expr::Path(path) = expression else {
        return None;
    };
    if path.path.segments.len() != 1 {
        return None;
    }
    path.path
        .segments
        .first()
        .map(|segment| segment.ident.to_string())
}

fn macro_body_sqlx_kind(tokens: &TokenStream, names: &SqlxNames) -> Option<SqlWrapperKind> {
    let mut identifiers = Vec::new();
    collect_token_identifiers(tokens.clone(), &mut identifiers);
    if identifiers
        .iter()
        .any(|identifier| names.resolve_symbol(identifier) == Some(SqlxSymbol::Query))
        || identifiers
            .windows(2)
            .any(|window| names.is_crate_name(&window[0]) && is_sqlx_query_name(window[1].as_str()))
    {
        return Some(SqlWrapperKind::Query);
    }
    identifiers
        .windows(2)
        .any(|window| {
            names.is_crate_name(&window[0]) && is_potential_sqlx_execution_name(window[1].as_str())
        })
        .then_some(SqlWrapperKind::Unknown)
}

fn collect_token_identifiers(tokens: TokenStream, identifiers: &mut Vec<String>) {
    for token in tokens {
        match token {
            TokenTree::Ident(ident) => identifiers.push(ident.to_string()),
            TokenTree::Group(group) => collect_token_identifiers(group.stream(), identifiers),
            _ => {}
        }
    }
}

fn collect_mutably_borrowed_identifiers(tokens: TokenStream, names: &mut BTreeSet<String>) {
    let tokens = tokens.into_iter().collect::<Vec<_>>();
    for window in tokens.windows(3) {
        if matches!(&window[0], TokenTree::Punct(punct) if punct.as_char() == '&')
            && matches!(&window[1], TokenTree::Ident(ident) if ident == "mut")
        {
            if let TokenTree::Ident(ident) = &window[2] {
                names.insert(ident.to_string());
            }
        }
    }
    for token in tokens {
        if let TokenTree::Group(group) = token {
            collect_mutably_borrowed_identifiers(group.stream(), names);
        }
    }
}

fn tokens_contain_ident(meta: &Meta, expected: &str) -> bool {
    let tokens = match meta {
        Meta::Path(_) => return false,
        Meta::List(list) => list.tokens.clone(),
        Meta::NameValue(_) => return false,
    };
    let mut identifiers = Vec::new();
    collect_token_identifiers(tokens, &mut identifiers);
    identifiers.iter().any(|ident| ident == expected)
}

fn compile_input_path(source_path: &Path, mac: &Macro) -> Result<PathBuf, String> {
    let literal = syn::parse2::<syn::LitStr>(mac.tokens.clone()).map_err(|error| {
        format!(
            "{}: compile-input macro requires one ordinary string literal: {error}",
            source_path.display()
        )
    })?;
    Ok(source_path
        .parent()
        .unwrap_or_else(|| Path::new("."))
        .join(literal.value()))
}

fn canonical_compile_input(path: &Path) -> Result<PathBuf, String> {
    path.canonicalize().map_err(|error| {
        format!(
            "cannot resolve Rust compile input {}: {error}",
            path.display()
        )
    })
}

fn sqlx_manifest_root(root: &Path) -> PathBuf {
    let parent = root.parent().unwrap_or_else(|| Path::new("."));
    if parent.file_name().is_some_and(|name| name == "src") {
        parent
            .parent()
            .unwrap_or_else(|| Path::new("."))
            .to_path_buf()
    } else {
        parent.to_path_buf()
    }
}

fn resolve_sqlx_query_file(roots: &[PathBuf], relative_path: &str) -> Result<PathBuf, String> {
    let mut matches = roots
        .iter()
        .map(|root| root.join(relative_path))
        .filter(|candidate| candidate.is_file())
        .filter_map(|candidate| candidate.canonicalize().ok())
        .collect::<BTreeSet<_>>();
    match matches.len() {
        1 => Ok(matches.pop_first().expect("one SQLx query file")),
        0 => Err(format!(
            "cannot resolve SQLx query file `{relative_path}` relative to a crate manifest root"
        )),
        _ => Err(format!(
            "SQLx query file `{relative_path}` resolves ambiguously across crate roots"
        )),
    }
}

fn module_dir_for(path: &Path) -> PathBuf {
    let parent = path.parent().unwrap_or_else(|| Path::new("."));
    match path.file_name().and_then(|name| name.to_str()) {
        Some("main.rs" | "lib.rs" | "mod.rs") => parent.to_path_buf(),
        _ => parent.join(path.file_stem().unwrap_or_default()),
    }
}

fn item_attrs(item: &Item) -> &[Attribute] {
    match item {
        Item::Const(item) => &item.attrs,
        Item::Enum(item) => &item.attrs,
        Item::ExternCrate(item) => &item.attrs,
        Item::Fn(item) => &item.attrs,
        Item::ForeignMod(item) => &item.attrs,
        Item::Impl(item) => &item.attrs,
        Item::Macro(item) => &item.attrs,
        Item::Mod(item) => &item.attrs,
        Item::Static(item) => &item.attrs,
        Item::Struct(item) => &item.attrs,
        Item::Trait(item) => &item.attrs,
        Item::TraitAlias(item) => &item.attrs,
        Item::Type(item) => &item.attrs,
        Item::Union(item) => &item.attrs,
        Item::Use(item) => &item.attrs,
        Item::Verbatim(_) => &[],
        _ => &[],
    }
}

fn is_test_only(attributes: &[Attribute]) -> bool {
    attributes.iter().any(|attribute| {
        attribute.path().is_ident("test")
            || (attribute.path().is_ident("cfg") && cfg_requires_test(&attribute.meta))
    })
}

fn cfg_requires_test(meta: &Meta) -> bool {
    let Meta::List(list) = meta else {
        return false;
    };
    let parser = Punctuated::<Meta, Token![,]>::parse_terminated;
    let Ok(arguments) = parser.parse2(list.tokens.clone()) else {
        return false;
    };
    if list.path.is_ident("cfg") {
        return arguments.first().is_some_and(cfg_meta_requires_test);
    }
    false
}

fn cfg_meta_requires_test(meta: &Meta) -> bool {
    match meta {
        Meta::Path(path) => path.is_ident("test"),
        Meta::List(list) if list.path.is_ident("all") => {
            parse_cfg_arguments(list).is_some_and(|items| items.iter().any(cfg_meta_requires_test))
        }
        Meta::List(list) if list.path.is_ident("any") => parse_cfg_arguments(list)
            .is_some_and(|items| !items.is_empty() && items.iter().all(cfg_meta_requires_test)),
        _ => false,
    }
}

fn parse_cfg_arguments(list: &syn::MetaList) -> Option<Vec<Meta>> {
    Punctuated::<Meta, Token![,]>::parse_terminated
        .parse2(list.tokens.clone())
        .ok()
        .map(|items| items.into_iter().collect())
}

fn macro_path_name(mac: &Macro) -> Option<String> {
    mac.path
        .segments
        .last()
        .map(|segment| segment.ident.to_string())
}

fn expression_line(source: &str, expression: &Expr) -> usize {
    let needle = match expression {
        Expr::Lit(literal) => match &literal.lit {
            Lit::Str(value) => value.token().to_string(),
            _ => return 1,
        },
        _ => return 1,
    };
    source
        .find(&needle)
        .map(|offset| {
            source[..offset]
                .bytes()
                .filter(|byte| *byte == b'\n')
                .count()
                + 1
        })
        .unwrap_or(1)
}

fn literal_line(source: &str, literal: &syn::LitStr) -> usize {
    let needle = literal.token().to_string();
    source
        .find(&needle)
        .map(|offset| {
            source[..offset]
                .bytes()
                .filter(|byte| *byte == b'\n')
                .count()
                + 1
        })
        .unwrap_or(1)
}
