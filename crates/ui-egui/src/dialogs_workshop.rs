//! Workshop front end; all design changes remain ordinary engine commands.
use crate::dialogs::Kind;
use crate::selection::{BODIES, EDGES, FACES, SelInput};
use crate::ui_kit::{self, Button, choice_row, text_row};
use crate::{SolveApp, scenario};
use serde_json::{Value, json};
use solidcraft_engine::Sel;

#[derive(Clone, Debug)]
pub struct Workshop {
    tab: usize,
    preset: usize,
    material: usize,
    template: usize,
    grain: usize,
    name: String,
    length: String,
    width: String,
    thickness: String,
    hole: String,
    layer: String,
    line: String,
    margin: String,
    catalogue: Value,
    report: Option<Value>,
    report_key: Option<String>,
    error: Option<String>,
    hardware: crate::dialogs_parts::Pt,
    wood_draft: [String; 4],
    pla_draft: [String; 4],
    wood_material: usize,
    furniture_template: usize,
    furniture_draft: [String; 4],
    travel: String,
    dowel_diameter: String,
    clearance: String,
    drilling_depth: String,
    dowel_count: String,
}

fn tr(id: &str) -> String {
    crate::i18n::tr(&format!("workshop.{id}")).to_string()
}

pub fn needs_picks(k: &Workshop) -> bool {
    matches!(k.tab, 2 | 3 | 4 | 5)
}

pub fn start(app: &SolveApp, id: &str) -> Option<(Kind, Vec<SelInput>)> {
    if id != "workshop.library" {
        return None;
    }
    let mut scratch = app.session.scratch();
    let (catalogue, error) = match scratch.execute("workshop.library", &json!({})) {
        Ok(value) => (value, None),
        Err(error) => (Value::Null, Some(error.to_string())),
    };
    Some((
        Kind::Workshop(Workshop {
            tab: 0,
            preset: 0,
            material: 0,
            template: 0,
            grain: 0,
            name: format!("{} {}", tr("board_name"), app.session.doc.components.len() + 1),
            length: "1200".into(),
            width: "300".into(),
            thickness: "18".into(),
            hole: "4.5".into(),
            layer: "0.2".into(),
            line: "0.42".into(),
            margin: "3".into(),
            catalogue,
            report: None,
            report_key: None,
            error,
            hardware: crate::dialogs_parts::Pt { family: 0, size: 0, length: None, name: String::new(), picture: None, lib: None },
            wood_draft: [format!("{} {}", tr("board_name"), app.session.doc.components.len() + 1), "1200".into(), "300".into(), "18".into()],
            pla_draft: [format!("{} {}", tr("part_name"), app.session.doc.components.len() + 1), "60".into(), "30".into(), "6".into()],
            wood_material: 0,
            furniture_template: 0,
            furniture_draft: [format!("{} {}", tr("furniture_name"), app.session.doc.components.len() + 1), "60".into(), "40".into(), "2".into()],
            travel: "110".into(),
            dowel_diameter: "6".into(),
            clearance: "0.2".into(),
            drilling_depth: "12".into(),
            dowel_count: "2".into(),
        }),
        vec![SelInput::new("Bodies", BODIES, true)],
    ))
}

fn number(value: &str) -> Result<f64, String> {
    value.trim().replace(',', ".").parse::<f64>().ok().filter(|v| v.is_finite()).ok_or_else(|| tr("number_error"))
}

fn field(ui: &mut egui::Ui, key: &str, value: &mut String) -> bool {
    let row = ui.scope(|ui| text_row(ui, &tr(key), value, ""));
    scenario::publish_handle(&format!("workshop:field:{key}"), egui::pos2(row.response.rect.right() - 24.0, row.response.rect.center().y));
    row.inner.0
}

fn picked(inputs: &[SelInput]) -> Vec<String> {
    inputs.iter().flat_map(|i| &i.items).filter_map(|s| if let Sel::Body { name } = s { Some(name.clone()) } else { None }).collect()
}

fn material_id(k: &Workshop) -> String {
    k.catalogue["materials"].get(k.material).and_then(|m| m["id"].as_str()).unwrap_or("pine").into()
}

pub fn commands(app: &SolveApp, k: &Workshop, inputs: &[SelInput]) -> Result<Vec<(String, Value)>, String> {
    if k.catalogue.is_null() {
        return Err(k.error.clone().unwrap_or_else(|| tr("catalogue_error")));
    }
    match k.tab {
        0 => Ok(vec![(
            "wood.board".into(),
            json!({"name":k.name,"material":material_id(k),"length_mm":number(&k.length)?,"width_mm":number(&k.width)?,"thickness_mm":number(&k.thickness)?,"grain":if k.grain==0 {"length"} else {"width"}}),
        )]),
        1 => {
            let length = number(&k.length)?;
            let width = if k.template == 1 { length } else { number(&k.width)? };
            Ok(vec![(
                "print.part".into(),
                json!({"name":k.name,"template":(["mounting_plate","spacer","angle_bracket"].get(k.template).unwrap_or(&"mounting_plate")),"length_mm":length,"width_mm":width,"thickness_mm":number(&k.thickness)?,"hole_diameter_mm":number(&k.hole)?}),
            )])
        }
        4 => crate::dialogs_parts::commands(app, &k.hardware, inputs),
        5 => {
            let bodies = picked(inputs);
            if bodies.len() != 2 {
                return Err(tr("joinery_selection"));
            }
            let count = k.dowel_count.trim().parse::<usize>().map_err(|_| tr("dowel_count_error"))?;
            if !(1..=16).contains(&count) {
                return Err(tr("dowel_count_error"));
            }
            let depth = number(&k.drilling_depth)?;
            Ok(vec![(
                "wood.joinery".into(),
                json!({"bodies":bodies,"count":count,
                "diameter_mm":number(&k.dowel_diameter)?,"clearance_mm":number(&k.clearance)?,"depths_mm":[depth,depth]}),
            )])
        }
        7 => Ok(vec![(
            "furniture.insert".into(),
            json!({"name":k.name,
            "template":if k.furniture_template == 0 {"butt_hinge"} else {"drawer_slide"},
            "length_mm":number(&k.length)?,"width_mm":number(&k.width)?,"thickness_mm":number(&k.thickness)?,"travel":number(&k.travel)?}),
        )]),
        _ => Ok(vec![("workshop.library".into(), json!({}))]),
    }
}

pub fn rows(app: &mut SolveApp, ui: &mut egui::Ui, k: &mut Workshop, inputs: &mut [SelInput]) -> bool {
    ui.horizontal_wrapped(|ui| {
        for (tab, key) in ["wood", "pla", "materials", "preflight", "hardware", "joinery", "cut_list", "furniture"].iter().enumerate() {
            let r = ui.selectable_label(k.tab == tab, tr(key));
            scenario::publish_handle(&format!("workshop:tab:{key}"), r.rect.center());
            if r.clicked() {
                ui.ctx().request_repaint();
                let draft = [k.name.clone(), k.length.clone(), k.width.clone(), k.thickness.clone()];
                if k.tab == 0 {
                    k.wood_draft = draft;
                    k.wood_material = k.material;
                } else if k.tab == 1 {
                    k.pla_draft = draft;
                } else if k.tab == 7 {
                    k.furniture_draft = draft;
                }
                k.tab = tab;
                k.report = None;
                k.error = None;
                if let Some(input) = inputs.first_mut() {
                    let accept = if tab == 4 { FACES | EDGES } else { BODIES };
                    if input.accept != accept {
                        input.items.clear();
                    }
                    input.accept = accept;
                    input.label = if tab == 4 { "parts.holes" } else { "Bodies" };
                }
                if tab == 0 || tab == 1 || tab == 7 {
                    let draft = match tab {
                        0 => &k.wood_draft,
                        1 => &k.pla_draft,
                        _ => &k.furniture_draft,
                    };
                    [k.name, k.length, k.width, k.thickness] = draft.clone();
                    if tab == 0 {
                        k.material = k.wood_material;
                    }
                }
            }
        }
    });
    ui.separator();
    ui.push_id(("workshop_content", k.tab), |ui| {
        let mut enter = false;
        if k.tab == 4 {
            return crate::dialogs_parts::rows(app, ui, &mut k.hardware, inputs);
        }
        if k.tab == 5 {
            ui_kit::text(ui, &tr("joinery_note"), ui_kit::Text::Note("joinery_note"));
            for body in picked(inputs) {
                ui.label(body);
            }
            if picked(inputs).len() != 2 {
                ui_kit::text(ui, &tr("joinery_selection"), ui_kit::Text::Note("joinery_selection"));
            }
            field(ui, "dowel_diameter", &mut k.dowel_diameter);
            field(ui, "clearance", &mut k.clearance);
            field(ui, "drilling_depth", &mut k.drilling_depth);
            field(ui, "dowel_count", &mut k.dowel_count);
        }
        if k.tab == 6 {
            ui_kit::text(ui, &tr("cut_list_note"), ui_kit::Text::Note("cut_list_note"));
            let report_key = format!("cut_list:{}", app.session.revision);
            if k.report_key.as_deref() != Some(report_key.as_str()) {
                k.report = None;
            }
            let refresh = ui_kit::button(ui, tr("refresh_cut_list"), Button::Normal);
            scenario::publish_handle("workshop:refresh_cut_list", refresh.rect.center());
            if refresh.clicked() {
                match app.run("wood.cut_list", json!({})) {
                    Ok(report) => {
                        k.report = Some(report);
                        k.report_key = Some(format!("cut_list:{}", app.session.revision));
                        k.error = None;
                    }
                    Err(error) => {
                        k.report = None;
                        k.error = Some(error.to_string());
                    }
                }
            }
            if let Some(report) = &k.report {
                if let Some(rows) = report["rows"].as_array() {
                    if rows.is_empty() {
                        ui.label(tr("no_stock"));
                    }
                    egui::ScrollArea::vertical().max_height(280.0).show(ui, |ui| {
                        for row in rows {
                            ui.label(format!("{} × {}", row["quantity"], row["component"].as_str().unwrap_or_default()));
                            ui.label(format!(
                                "{} × {} × {} mm · {}",
                                row["length_mm"],
                                row["width_mm"],
                                row["thickness_mm"],
                                row["material"].as_str().unwrap_or_default()
                            ));
                            ui.label(tr(match row["grain_axis"].as_str() {
                                Some("width") => "grain_width",
                                Some("length") => "grain_length",
                                _ => "grain_unverified",
                            }));
                            if row["shape_status"] != "rectangular_blank" {
                                ui_kit::text(ui, &tr("machined_stock"), ui_kit::Text::Note("machined_stock"));
                            }
                            ui.separator();
                        }
                    });
                }
                ui_kit::text(ui, &tr("cut_list_limits"), ui_kit::Text::Note("cut_list_limits"));
            }
        }
        if k.tab == 7 {
            let labels = [tr("butt_hinge"), tr("drawer_slide")];
            let previous = k.furniture_template;
            let response = choice_row(ui, &tr("template"), "workshop_furniture_template", &mut k.furniture_template, &[&labels[0], &labels[1]]);
            scenario::publish_handle("workshop:furniture_template", response.rect.center());
            if previous != k.furniture_template {
                let defaults = if k.furniture_template == 0 { ["60", "40", "2", "110"] } else { ["400", "20", "10", "300"] };
                k.length = defaults[0].into();
                k.width = defaults[1].into();
                k.thickness = defaults[2].into();
                k.travel = defaults[3].into();
            }
            ui_kit::text(ui, &tr("furniture_note"), ui_kit::Text::Note("furniture_note"));
            field(ui, "name", &mut k.name);
            field(ui, "length", &mut k.length);
            field(ui, "width", &mut k.width);
            field(ui, "thickness", &mut k.thickness);
            field(ui, if k.furniture_template == 0 { "opening_angle" } else { "sliding_travel" }, &mut k.travel);
        }
        if k.tab == 0 {
            let labels: Vec<_> = ["shelf", "sheet", "back_panel", "batten", "worktop"].iter().map(|s| tr(s)).collect();
            let labels: Vec<_> = labels.iter().map(String::as_str).collect();
            let old = k.preset;
            let response = choice_row(ui, &tr("stock_format"), "workshop_stock", &mut k.preset, &labels);
            scenario::publish_handle("workshop:stock_format", response.rect.center());
            if old != k.preset
                && let Some(p) = k.catalogue["boards"].get(k.preset)
            {
                k.length = p["length_mm"].to_string();
                k.width = p["width_mm"].to_string();
                k.thickness = p["thickness_mm"].to_string();
                k.material = k.catalogue["materials"].as_array().and_then(|a| a.iter().position(|m| m["id"] == p["material"])).unwrap_or(0);
            }
            ui_kit::text(ui, &tr("stock_note"), ui_kit::Text::Note("stock_note"));
        }
        if k.tab == 1 {
            let labels: Vec<_> = ["mounting_plate", "spacer", "angle_bracket"].iter().map(|s| tr(s)).collect();
            let labels: Vec<_> = labels.iter().map(String::as_str).collect();
            let response = choice_row(ui, &tr("template"), "workshop_template", &mut k.template, &labels);
            scenario::publish_handle("workshop:template", response.rect.center());
            ui_kit::text(ui, &tr("pla_note"), ui_kit::Text::Note("pla_note"));
        }
        if k.tab == 0 || k.tab == 2 {
            let count = if k.tab == 0 { 10 } else { 11 };
            let ids: Vec<_> = k.catalogue["materials"].as_array().into_iter().flatten().take(count).filter_map(|m| m["id"].as_str()).collect();
            let labels: Vec<_> = ids.iter().map(|id| tr(id)).collect();
            let labels: Vec<_> = labels.iter().map(String::as_str).collect();
            k.material = k.material.min(labels.len().saturating_sub(1));
            let response = choice_row(ui, &tr("material_label"), "workshop_material", &mut k.material, &labels);
            scenario::publish_handle("workshop:material", response.rect.center());
            let grain = [tr("grain_length"), tr("grain_width")];
            if k.tab == 0 {
                let response = choice_row(ui, &tr("grain_label"), "workshop_grain", &mut k.grain, &[&grain[0], &grain[1]]);
                scenario::publish_handle("workshop:grain", response.rect.center());
            }
            if k.tab == 2 {
                ui_kit::text(ui, &tr("material_note"), ui_kit::Text::Note("material_note"));
                let r = ui_kit::button(ui, tr("apply_material"), Button::Enabled(!picked(inputs).is_empty()));
                scenario::publish_handle("workshop:apply_material", r.rect.center());
                if r.clicked() {
                    k.error = app.run("workshop.material", json!({"material":material_id(k),"bodies":picked(inputs)})).err().map(|e| e.to_string());
                }
            }
        }
        if k.tab <= 1 {
            enter |= field(ui, "name", &mut k.name);
            let spacer = k.tab == 1 && k.template == 1;
            enter |= field(ui, if spacer { "diameter" } else { "length" }, &mut k.length);
            if !spacer {
                enter |= field(ui, "width", &mut k.width);
            }
            enter |= field(ui, if spacer { "height" } else { "thickness" }, &mut k.thickness);
            if k.tab == 1 {
                enter |= field(ui, "hole", &mut k.hole);
                let width = if spacer { number(&k.length) } else { number(&k.width) };
                if let (Ok(length), Ok(width), Ok(thickness)) = (number(&k.length), width, number(&k.thickness)) {
                    let size = match k.template {
                        1 => [length, length, thickness],
                        2 => [length, width, width],
                        _ => [length, width, thickness],
                    };
                    if size[0] > 250.0 || size[1] > 250.0 || size[2] > 256.0 {
                        ui_kit::text(ui, &tr("outside_build_volume_in_current_orientation"), ui_kit::Text::Note("template_size_warning"));
                    }
                }
            }
            ui_kit::text(ui, &tr("create_note"), ui_kit::Text::Hint("create_note"));
        }
        if k.tab == 3 {
            ui_kit::text(ui, "Bambu Lab A1 · PLA · 0.4 mm · 256 × 256 × 256 mm", ui_kit::Text::Note("printer_profile"));
            field(ui, "layer", &mut k.layer);
            field(ui, "line", &mut k.line);
            field(ui, "margin", &mut k.margin);
            let bodies = picked(inputs);
            let report_key = format!("{:?}|{}|{}|{}|{}", bodies, k.layer, k.line, k.margin, app.session.revision);
            if k.report_key.as_ref() != Some(&report_key) {
                k.report = None;
            }
            let r = ui_kit::button(ui, tr("check"), Button::Enabled(!bodies.is_empty()));
            scenario::publish_handle("workshop:check", r.rect.center());
            if r.clicked() {
                let report = (|| {
                    let (layer, line, margin) = (number(&k.layer)?, number(&k.line)?, number(&k.margin)?);
                    if !(0.08..=0.28).contains(&layer) {
                        return Err(tr("layer_error"));
                    }
                    if !(0.2..=1.0).contains(&line) {
                        return Err(tr("line_error"));
                    }
                    if !(0.0..=100.0).contains(&margin) {
                        return Err(tr("margin_error"));
                    }
                    let params = json!({"bodies":bodies,"printer":"bambu_a1_04","layer_height_mm":layer,"line_width_mm":line,"bed_margin_mm":margin});
                    app.run("print.check", params).map_err(|e| e.to_string())
                })();
                match report {
                    Ok(v) => {
                        k.report = Some(v);
                        k.report_key = Some(format!("{:?}|{}|{}|{}|{}", bodies, k.layer, k.line, k.margin, app.session.revision));
                        k.error = None;
                    }
                    Err(e) => {
                        k.report = None;
                        k.error = Some(e);
                    }
                }
            }
            if let Some(report) = &k.report {
                let ready = report["ready_for_slicer"] == true;
                ui_kit::text(ui, &tr(if ready { "needs_slicing" } else { "blocked" }), ui_kit::Text::Note("preflight_status"));
                for body in report["bodies"].as_array().into_iter().flatten() {
                    ui.label(body["body"].as_str().unwrap_or_default());
                    for issue in body["blockers"].as_array().into_iter().flatten().filter_map(Value::as_str) {
                        ui.label(tr(issue));
                    }
                    for warning in body["warnings"].as_array().into_iter().flatten().filter_map(Value::as_str) {
                        ui.label(tr(warning));
                    }
                }
                ui_kit::text(ui, &tr("unverified"), ui_kit::Text::Note("unverified"));
                let send = ui_kit::button(ui, tr("send_bambu"), Button::Enabled(ready && app.services.pick_program.is_some()));
                scenario::publish_handle("workshop:send_bambu", send.rect.center());
                if send.clicked() {
                    crate::dialogs_save_mesh::send_to_slicer(app, json!({"slicer":"bambu","bodies":bodies,"format":"3mf"}));
                }
            }
            ui_kit::text(ui, &tr("slicer_note"), ui_kit::Text::Hint("slicer_note"));
        }
        if k.tab < 5 {
            ui_kit::text(ui, &tr("hardware_note"), ui_kit::Text::Hint("hardware_note"));
        }
        if let Some(error) = &k.error {
            ui_kit::text(ui, error, ui_kit::Text::Note("workshop_error"));
        }
        enter
    })
    .inner
}
