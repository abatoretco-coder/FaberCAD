//! Workshop stock, procedural templates and printer preflight contracts.
use schemars::JsonSchema;
use serde::{Deserialize, Serialize};
use serde_json::Value;

#[derive(Debug, Deserialize, JsonSchema)]
#[serde(deny_unknown_fields)]
pub struct LibraryParams {}

#[derive(Debug, Deserialize, JsonSchema)]
#[serde(deny_unknown_fields)]
pub struct BoardParams {
    pub name: String,
    pub material: String,
    pub length_mm: f64,
    pub width_mm: f64,
    pub thickness_mm: f64,
    #[serde(default)]
    pub grain: Option<String>,
}

#[derive(Debug, Deserialize, JsonSchema)]
#[serde(deny_unknown_fields)]
pub struct PartParams {
    pub name: String,
    pub template: String,
    pub length_mm: f64,
    pub width_mm: f64,
    pub thickness_mm: f64,
    pub hole_diameter_mm: f64,
}

#[derive(Debug, Deserialize, JsonSchema)]
#[serde(deny_unknown_fields)]
pub struct CheckParams {
    pub bodies: Vec<String>,
    #[serde(default)]
    pub printer: Option<String>,
    #[serde(default)]
    pub layer_height_mm: Option<f64>,
    #[serde(default)]
    pub line_width_mm: Option<f64>,
    #[serde(default)]
    pub bed_margin_mm: Option<f64>,
}

#[derive(Debug, Deserialize, JsonSchema)]
#[serde(deny_unknown_fields)]
pub struct MaterialParams {
    pub material: String,
    pub bodies: Vec<String>,
}

#[derive(Debug, Serialize, JsonSchema)]
pub struct AppliedMaterial {
    pub material: String,
    pub bodies: Vec<String>,
}

#[derive(Debug, Serialize, JsonSchema)]
pub struct Created {
    pub component: String,
    pub body: String,
    pub material: String,
    pub geometry_provenance: String,
    pub print_preflight: Option<Value>,
}

#[derive(Debug, Serialize, JsonSchema)]
pub struct Catalogue {
    pub furniture_catalogue: Value,
    pub materials: Vec<Value>,
    pub boards: Vec<Value>,
    pub printable_templates: Vec<String>,
    pub hardware: Value,
    pub printer: Value,
}

#[derive(Debug, Serialize, JsonSchema)]
pub struct PrintReport {
    pub printer: Value,
    pub bodies: Vec<Value>,
    pub ready_for_slicer: bool,
    pub printable: Option<bool>,
    pub unverified: Vec<String>,
}
