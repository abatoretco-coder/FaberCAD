//! Run the engine's actual workshop tests against its production library.
use serde_json::json;
use solidcraft_engine::Session;

#[path = "../../crates/engine/src/cmd/workshop_tests.rs"]
mod tests;
