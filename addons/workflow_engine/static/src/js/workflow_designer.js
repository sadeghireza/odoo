/** @odoo-module **/

import { Component, onWillStart, useRef, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { registry } from "@web/core/registry";
import { buildExpressionFromRules, parseExpressionToRules } from "./condition_builder";

class WorkflowDesigner extends Component {
    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.svgRef = useRef("svg");
        this.versionStorageKey = "workflow_engine.designer.version_id";
        this.state = useState({
            versions: [],
            selectedVersionId: null,
            selectedVersionState: null,
            states: [],
            transitions: [],
            positions: {},
            draggingId: null,
            selectedStateId: null,
            selectedTransitionId: null,
            selectedTransitionSourceType: null,
            linkMode: false,
            linkSourceId: null,
            targetModel: null,
            modelFields: [],
            modelFieldsMap: {},
            builderRules: [
                { id: 1, field: "", operator: "=", value: "", logic: "and" },
            ],
            builderDirty: false,
            builderRulesMap: {},
            builderModalOpen: false,
            builderDraftRules: [],
            builderDraftIsElse: false,
            buildSidebarMode: "expanded",
            ruleCounter: 1,
            stateForm: {
                name: "",
                code: "",
                type: "task",
                approval_mode: "sequential",
                parallel_policy: "all",
                min_approvals: 1,
            },
            transitionForm: {
                name: "",
                trigger: "manual",
                transition_type: "normal",
                branch_expression: "",
                branch_is_else: false,
            },
            zoom: 1,
            pan: { x: 0, y: 0 },
            panning: false,
            panStart: { x: 0, y: 0 },
            panOrigin: { x: 0, y: 0 },
            dragOffset: { x: 0, y: 0 },
            loading: false,
            gridSize: 20,
        });

        onWillStart(async () => {
            await this.loadVersions();
        });
    }

    async loadVersions() {
        this.state.loading = true;
        const versions = await this.orm.searchRead(
            "workflow.process.version",
            [],
            ["name", "process_id", "version", "state"]
        );
        this.state.versions = versions.map((v) => ({
            id: v.id,
            label: `${v.process_id?.[1] || "Process"} / v${v.version} [${v.state}]`,
            state: v.state,
        }));
        const storedId = this.getStoredVersionId();
        const stored = storedId ? this.state.versions.find((v) => v.id === storedId) : null;
        const active = this.state.versions.find((v) => v.state === "active");
        const selected = stored || active || this.state.versions[0];
        if (selected) {
            this.state.selectedVersionId = selected.id;
            this.state.selectedVersionState = selected.state;
            await this.loadGraph(selected.id);
        }
        this.state.loading = false;
    }

    async loadGraph(versionId) {
        if (!versionId) {
            return;
        }
        this.state.loading = true;
        await this.loadTargetModelFields(versionId);
        const states = await this.orm.searchRead(
            "workflow.state",
            [["version_id", "=", versionId]],
            [
                "name",
                "code",
                "type",
                "approval_mode",
                "parallel_policy",
                "min_approvals",
                "sequence",
                "ui_x",
                "ui_y",
            ]
        );
        const transitions = await this.orm.searchRead(
            "workflow.transition",
            [["version_id", "=", versionId]],
            [
                "name",
                "source_state_id",
                "dest_state_id",
                "trigger",
                "transition_type",
                "branch_expression",
                "branch_is_else",
            ]
        );
        this.state.states = states;
        this.state.transitions = transitions;
        this.state.positions = this.buildPositions(states);
        if (this.state.selectedStateId) {
            this.selectState(this.state.selectedStateId);
        }
        if (this.state.selectedTransitionId && !this.state.builderDirty) {
            this.selectTransition(this.state.selectedTransitionId);
        }
        this.state.loading = false;
    }

    async loadTargetModelFields(versionId) {
        const version = await this.orm.read(
            "workflow.process.version",
            [versionId],
            ["process_id"]
        );
        const processId = version?.[0]?.process_id?.[0];
        if (!processId) {
            this.state.targetModel = null;
            this.state.modelFields = [];
            this.state.modelFieldsMap = {};
            return;
        }
        const process = await this.orm.read(
            "workflow.process",
            [processId],
            ["target_model_id"]
        );
        const target = process?.[0]?.target_model_id;
        if (!target) {
            this.state.targetModel = null;
            this.state.modelFields = [];
            this.state.modelFieldsMap = {};
            return;
        }
        const modelInfo = await this.orm.read(
            "ir.model",
            [target[0]],
            ["model", "name"]
        );
        const modelName = modelInfo?.[0]?.model;
        this.state.targetModel = {
            id: target[0],
            name: modelInfo?.[0]?.name || target[1],
            model: modelName,
        };
        if (!modelName) {
            this.state.modelFields = [];
            this.state.modelFieldsMap = {};
            return;
        }
        const fields = await this.orm.call(
            modelName,
            "fields_get",
            [[], ["string", "type", "selection", "relation"]]
        );
        const entries = Object.entries(fields || {});
        const fieldList = entries.map(([name, info]) => ({
            name,
            string: info.string || name,
            type: info.type || "char",
            selection: info.selection || [],
            relation: info.relation || null,
        }));
        fieldList.sort((a, b) => a.string.localeCompare(b.string));
        this.state.modelFields = fieldList;
        const fieldMap = {};
        for (const field of fieldList) {
            fieldMap[field.name] = field;
        }
        this.state.modelFieldsMap = fieldMap;
    }

    buildPositions(states) {
        const positions = {};
        const colWidth = 220;
        const rowHeight = 140;
        let col = 0;
        let row = 0;
        const sorted = [...states].sort((a, b) => a.sequence - b.sequence || a.id - b.id);
        for (const state of sorted) {
            if (state.ui_x !== false && state.ui_x !== null && state.ui_y !== false && state.ui_y !== null) {
                positions[state.id] = this.snapToGrid({ x: state.ui_x, y: state.ui_y });
                continue;
            }
            positions[state.id] = this.snapToGrid({ x: 100 + col * colWidth, y: 80 + row * rowHeight });
            col += 1;
            if (col >= 4) {
                col = 0;
                row += 1;
            }
        }
        return positions;
    }

    getStateById(stateId) {
        return this.state.states.find((state) => state.id === stateId) || null;
    }

    onVersionChange(ev) {
        const versionId = parseInt(ev.target.value, 10);
        this.state.selectedVersionId = versionId;
        const selected = this.state.versions.find((v) => v.id === versionId);
        this.state.selectedVersionState = selected?.state || null;
        this.storeSelectedVersionId(versionId);
        this.loadGraph(versionId);
    }

    getStoredVersionId() {
        try {
            const raw = window.localStorage.getItem(this.versionStorageKey);
            const parsed = parseInt(raw || "0", 10);
            return Number.isNaN(parsed) ? null : parsed;
        } catch {
            return null;
        }
    }

    storeSelectedVersionId(versionId) {
        try {
            window.localStorage.setItem(this.versionStorageKey, String(versionId));
        } catch {
            // Ignore storage errors (e.g., private mode).
        }
    }

    reloadGraph() {
        this.loadGraph(this.state.selectedVersionId);
    }

    toggleBuildSidebar() {
        this.state.buildSidebarMode = this.state.buildSidebarMode === "compact" ? "expanded" : "compact";
    }

    async createRevision() {
        const versionId = this.state.selectedVersionId;
        if (!versionId) {
            return;
        }
        const newVersionId = await this.orm.call(
            "workflow.process.version",
            "create_revision",
            [versionId]
        );
        await this.loadVersions();
        this.state.selectedVersionId = newVersionId;
        this.storeSelectedVersionId(newVersionId);
        await this.loadGraph(newVersionId);
        this.notification.add("New revision created", { type: "success" });
    }

    async activateVersion() {
        const versionId = this.state.selectedVersionId;
        if (!versionId) {
            return;
        }
        await this.orm.call("workflow.process.version", "activate_version", [versionId]);
        await this.loadVersions();
        this.notification.add("Version activated", { type: "success" });
    }

    toggleLinkMode() {
        this.state.linkMode = !this.state.linkMode;
        this.state.linkSourceId = null;
        if (this.state.linkMode) {
            this.notification.add("Select source state", { type: "info" });
        }
    }

    useSelectTool() {
        this.state.linkMode = false;
        this.state.linkSourceId = null;
        this.notification.add("Select mode", { type: "info" });
    }

    selectState(stateId) {
        const state = this.state.states.find((s) => s.id === stateId);
        if (!state) {
            return;
        }
        this.state.selectedStateId = stateId;
        this.state.selectedTransitionId = null;
        this.state.stateForm = {
            name: state.name || "",
            code: state.code || "",
            type: state.type || "task",
            approval_mode: state.approval_mode || "sequential",
            parallel_policy: state.parallel_policy || "all",
            min_approvals: state.min_approvals || 1,
        };
    }

    async selectTransition(transitionId) {
        if (
            this.state.selectedTransitionId === transitionId
            && this.state.builderRules.length
            && this.state.builderDirty
        ) {
            return;
        }
        const transition = this.state.transitions.find((t) => t.id === transitionId);
        if (!transition) {
            return;
        }
        this.state.selectedTransitionId = transitionId;
        this.state.selectedStateId = null;
        const sourceId = transition.source_state_id?.[0];
        const sourceState = sourceId ? this.getStateById(sourceId) : null;
        this.state.selectedTransitionSourceType = sourceState?.type || null;
        const conditionExpression = sourceState?.type === "condition"
            ? (transition.branch_expression || "")
            : "";
        this.state.transitionForm = {
            name: transition.name || "",
            trigger: transition.trigger || "manual",
            transition_type: transition.transition_type || "normal",
            branch_expression: conditionExpression,
            branch_is_else: transition.branch_is_else || false,
        };
        const cached = this.state.builderRulesMap[transitionId];
        if (cached) {
            this.state.builderRules = cached.rules;
            this.state.builderDirty = cached.dirty;
        } else {
            const rules = this.withRuleIds(parseExpressionToRules(conditionExpression));
            this.state.builderRules = rules;
            this.state.builderDirty = false;
            this.state.builderRulesMap[transitionId] = { rules, dirty: false };
        }
    }

    async saveState() {
        const stateId = this.state.selectedStateId;
        if (!stateId) {
            return;
        }
        const vals = {
            name: this.state.stateForm.name,
            code: this.state.stateForm.code,
            type: this.state.stateForm.type,
            approval_mode: this.state.stateForm.approval_mode,
            parallel_policy: this.state.stateForm.parallel_policy,
            min_approvals: this.state.stateForm.min_approvals,
        };
        await this.orm.write("workflow.state", [stateId], vals);
        this.notification.add("State saved", { type: "success" });
        await this.loadGraph(this.state.selectedVersionId);
        this.selectState(stateId);
    }

    async saveTransition() {
        const transitionId = this.state.selectedTransitionId;
        if (!transitionId) {
            return;
        }
        const vals = {
            name: this.state.transitionForm.name,
            trigger: this.state.transitionForm.trigger,
            transition_type: this.state.transitionForm.transition_type,
        };
        await this.orm.write("workflow.transition", [transitionId], vals);
        this.notification.add("Transition saved", { type: "success" });
        await this.loadGraph(this.state.selectedVersionId);
        await this.selectTransition(transitionId);
    }

    updateStateField(ev) {
        const field = ev.currentTarget?.dataset?.field;
        if (!field) {
            return;
        }
        this.state.stateForm[field] = ev.target.value;
        if (field === "type" && ev.target.value === "condition") {
            this.state.stateForm.approval_mode = "none";
            this.state.stateForm.parallel_policy = "all";
            this.state.stateForm.min_approvals = 1;
        }
    }

    updateStateNumber(ev) {
        const field = ev.currentTarget?.dataset?.field;
        if (!field) {
            return;
        }
        this.state.stateForm[field] = parseInt(ev.target.value || "0", 10);
    }

    async openBranchEditor(ev) {
        const transitionId = parseInt(ev.currentTarget?.dataset?.transitionId || "0", 10);
        if (!transitionId) {
            return;
        }
        await this.selectTransition(transitionId);
        this.openBuilderModal();
    }

    updateTransitionField(ev) {
        const field = ev.currentTarget?.dataset?.field;
        if (!field) {
            return;
        }
        this.state.transitionForm[field] = ev.target.value;
    }

    openBuilderModal() {
        const transitionId = this.state.selectedTransitionId;
        if (!transitionId) {
            this.notification.add("Select a transition first", { type: "warning" });
            return;
        }
        const transition = this.state.transitions.find((t) => t.id === transitionId);
        const sourceId = transition?.source_state_id?.[0];
        const sourceState = sourceId ? this.getStateById(sourceId) : null;
        if (!sourceState || sourceState.type !== "condition") {
            this.notification.add("Branch conditions are only available on condition nodes", { type: "warning" });
            return;
        }
        const cached = this.state.builderRulesMap[transitionId];
        const expression = this.state.transitionForm.branch_expression || "";
        const rules = cached
            ? cached.rules
            : this.withRuleIds(parseExpressionToRules(expression));
        this.state.builderDraftRules = rules.map((rule, index) => ({
            ...rule,
            logic: index > 0 ? (rule.logic || "and") : "and",
        }));
        this.state.builderDraftIsElse = this.state.transitionForm.branch_is_else || false;
        if (!this.state.builderDraftRules.length) {
            this.state.builderDraftRules = [{
                id: this.nextRuleId(true),
                field: "",
                operator: "=",
                value: "",
                logic: "and",
            }];
        }
        this.state.builderModalOpen = true;
    }

    closeBuilderModal() {
        this.state.builderModalOpen = false;
        this.state.builderDraftRules = [];
        this.state.builderDraftIsElse = false;
    }

    addRule() {
        const logic = this.state.builderDraftRules.length ? "and" : "and";
        const id = this.nextRuleId();
        this.state.builderDraftRules.push({ id, field: "", operator: "=", value: "", logic });
    }

    removeRule(ev) {
        const index = parseInt(ev.currentTarget?.dataset?.index || "-1", 10);
        if (index < 0) {
            return;
        }
        this.state.builderDraftRules.splice(index, 1);
        if (!this.state.builderDraftRules.length) {
            const id = this.nextRuleId();
            this.state.builderDraftRules.push({ id, field: "", operator: "=", value: "", logic: "and" });
        }
    }

    async saveCondition() {
        const transitionId = this.state.selectedTransitionId;
        if (!transitionId) {
            return;
        }
        const draftRules = this.state.builderDraftRules;
        const transition = this.state.transitions.find((t) => t.id === transitionId);
        const sourceId = transition?.source_state_id?.[0];
        if (!transition || !sourceId) {
            return;
        }
        if (this.state.builderDraftIsElse) {
            const elseExists = this.state.transitions.some((t) =>
                t.id !== transitionId
                && t.source_state_id?.[0] === sourceId
                && t.branch_is_else
            );
            if (elseExists) {
                this.notification.add("Only one ELSE branch is allowed", { type: "danger" });
                return;
            }
            await this.orm.write("workflow.transition", [transitionId], {
                branch_expression: "",
                branch_is_else: true,
            });
            transition.branch_expression = "";
            transition.branch_is_else = true;
            this.state.transitionForm.branch_expression = "";
            this.state.transitionForm.branch_is_else = true;
            this.state.builderRules = [];
            this.state.builderRulesMap[transitionId] = { rules: [], dirty: false };
            this.notification.add("Branch saved", { type: "success" });
            this.state.builderDirty = false;
            this.state.builderModalOpen = false;
            this.state.builderDraftRules = [];
            this.state.builderDraftIsElse = false;
            return;
        }
        let invalidIndex = -1;
        let invalidReason = "";
        let validCount = 0;
        draftRules.some((rule, index) => {
            const fieldValue = rule.field || "";
            const operatorValue = rule.operator || "";
            const valueValue = rule.value;
            const hasValue = valueValue !== null && valueValue !== undefined && (typeof valueValue !== "string" || valueValue.trim() !== "");
            const hasAny = Boolean(fieldValue || operatorValue || hasValue);
            if (!hasAny) {
                return false;
            }
            if (!fieldValue || !operatorValue) {
                invalidIndex = index;
                invalidReason = !fieldValue ? "field" : "operator";
                return true;
            }
            if (operatorValue === "is_set" || operatorValue === "is_not_set") {
                validCount += 1;
                return false;
            }
            if (!hasValue) {
                invalidIndex = index;
                invalidReason = "value";
                return true;
            }
            validCount += 1;
            return false;
        });
        if (invalidIndex !== -1) {
            const line = invalidIndex + 1;
            const label = invalidReason ? ` (${invalidReason})` : "";
            const badRule = draftRules[invalidIndex] || {};
            const fieldInfo = badRule.field ? this.state.modelFieldsMap[badRule.field] : null;
            const fieldLabel = fieldInfo?.string || badRule.field || "<empty>";
            const operatorLabel = badRule.operator || "<empty>";
            const valueLabel = (badRule.value ?? "") === "" ? "<empty>" : badRule.value;
            const details = `Field: ${fieldLabel}, Operator: ${operatorLabel}, Value: ${valueLabel}`;
            this.notification.add(`Please complete rule ${line}${label} before saving. ${details}`, { type: "danger" });
            return;
        }
        if (!validCount) {
            this.notification.add("Add at least one rule before saving", { type: "danger" });
            return;
        }
        const expression = buildExpressionFromRules(draftRules, this.state.modelFieldsMap);
        await this.orm.write("workflow.transition", [transitionId], {
            branch_expression: expression,
            branch_is_else: false,
        });
        transition.branch_expression = expression;
        transition.branch_is_else = false;
        this.state.transitionForm.branch_expression = expression;
        this.state.transitionForm.branch_is_else = false;
        const savedRules = draftRules.map((rule) => ({ ...rule }));
        this.state.builderRules = savedRules;
        this.state.builderRulesMap[transitionId] = { rules: savedRules, dirty: false };
        const elseExists = this.state.transitions.some((t) =>
            t.source_state_id?.[0] === sourceId && t.branch_is_else
        );
        if (!elseExists) {
            this.notification.add("Add an ELSE branch for this condition node", { type: "warning" });
        }
        this.notification.add("Branch saved", { type: "success" });
        this.state.builderDirty = false;
        this.state.builderModalOpen = false;
        this.state.builderDraftRules = [];
        this.state.builderDraftIsElse = false;
    }

    getFieldInfo(fieldName) {
        return this.state.modelFieldsMap[fieldName] || null;
    }

    nextRuleId(reset = false) {
        if (reset) {
            this.state.ruleCounter += 1;
            return this.state.ruleCounter;
        }
        this.state.ruleCounter += 1;
        return this.state.ruleCounter;
    }

    withRuleIds(rules) {
        if (!rules.length) {
            const id = this.nextRuleId(true);
            return [{ id, field: "", operator: "=", value: "", logic: "and" }];
        }
        return rules.map((rule) => ({
            id: this.nextRuleId(true),
            field: rule.field,
            operator: rule.operator,
            value: rule.value,
            logic: rule.logic || "and",
        }));
    }


    zoomIn() {
        this.setZoom(this.state.zoom + 0.1);
    }

    zoomOut() {
        this.setZoom(this.state.zoom - 0.1);
    }

    resetView() {
        this.state.zoom = 1;
        this.state.pan = { x: 0, y: 0 };
    }

    setZoom(value) {
        const next = Math.min(2.5, Math.max(0.4, value));
        this.state.zoom = Math.round(next * 100) / 100;
    }

    async addState() {
        const versionId = this.state.selectedVersionId;
        if (!versionId) {
            return;
        }
        const code = this.buildNextCode();
        const pos = this.getNextPosition();
        await this.orm.create("workflow.state", [{
            name: "New State",
            code,
            version_id: versionId,
            type: "task",
            approval_mode: "sequential",
            ui_x: pos.x,
            ui_y: pos.y,
        }]);
        this.notification.add("State created", { type: "success" });
        await this.loadGraph(versionId);
    }

    async addConditionNode() {
        const versionId = this.state.selectedVersionId;
        if (!versionId) {
            return;
        }
        const code = this.buildNextCode();
        const pos = this.getNextPosition();
        await this.orm.create("workflow.state", [{
            name: "Condition",
            code,
            version_id: versionId,
            type: "condition",
            approval_mode: "none",
            ui_x: pos.x,
            ui_y: pos.y,
        }]);
        this.notification.add("Condition node created", { type: "success" });
        await this.loadGraph(versionId);
    }

    async setStartState() {
        const versionId = this.state.selectedVersionId;
        const stateId = this.state.selectedStateId;
        if (!versionId || !stateId) {
            this.notification.add("Select a state first", { type: "warning" });
            return;
        }
        const states = await this.orm.searchRead(
            "workflow.state",
            [["version_id", "=", versionId]],
            ["id", "type"]
        );
        const toReset = states.filter((s) => s.id !== stateId && s.type === "start").map((s) => s.id);
        if (toReset.length) {
            await this.orm.write("workflow.state", toReset, { type: "task" });
        }
        await this.orm.write("workflow.state", [stateId], { type: "start" });
        this.notification.add("Start state updated", { type: "success" });
        await this.loadGraph(versionId);
    }

    buildNextCode() {
        const existing = new Set(this.state.states.map((s) => s.code));
        let index = this.state.states.length + 1;
        let code = `state_${index}`;
        while (existing.has(code)) {
            index += 1;
            code = `state_${index}`;
        }
        return code;
    }

    getNextPosition(anchorStateId) {
        if (anchorStateId && this.state.positions[anchorStateId]) {
            const anchor = this.state.positions[anchorStateId];
            return this.snapToGrid({ x: anchor.x + 180, y: anchor.y });
        }
        const count = this.state.states.length;
        return this.snapToGrid({ x: 100 + (count % 4) * 220, y: 80 + Math.floor(count / 4) * 140 });
    }

    snapToGrid(pos) {
        const size = this.state.gridSize || 20;
        return {
            x: Math.round(pos.x / size) * size,
            y: Math.round(pos.y / size) * size,
        };
    }

    getEdgePoints(transition) {
        const sourceId = transition.source_state_id?.[0];
        const destId = transition.dest_state_id?.[0];
        const src = sourceId ? this.state.positions[sourceId] : null;
        const dst = destId ? this.state.positions[destId] : null;
        if (!src || !dst) {
            return null;
        }
        const sourceState = this.getStateById(sourceId);
        const destState = this.getStateById(destId);
        const srcCenter = { x: src.x + 60, y: src.y + 26 };
        const dstCenter = { x: dst.x + 60, y: dst.y + 26 };
        const srcPorts = this.getPortsForState(sourceState, src);
        const dstPorts = this.getPortsForState(destState, dst);
        const srcPoint = this.pickClosestPort(srcPorts, dstCenter) || srcCenter;
        const dstPoint = this.pickClosestPort(dstPorts, srcCenter) || dstCenter;
        return {
            sx: srcPoint.x,
            sy: srcPoint.y,
            dx: dstPoint.x,
            dy: dstPoint.y,
        };
    }

    getPortsForState(state, pos) {
        if (!state || !pos) {
            return [];
        }
        if (state.type === "condition") {
            return [
                { x: pos.x + 60, y: pos.y },
                { x: pos.x + 120, y: pos.y + 26 },
                { x: pos.x + 60, y: pos.y + 52 },
                { x: pos.x, y: pos.y + 26 },
            ];
        }
        return [
            { x: pos.x, y: pos.y },
            { x: pos.x + 60, y: pos.y },
            { x: pos.x + 120, y: pos.y },
            { x: pos.x + 120, y: pos.y + 26 },
            { x: pos.x + 120, y: pos.y + 52 },
            { x: pos.x + 60, y: pos.y + 52 },
            { x: pos.x, y: pos.y + 52 },
            { x: pos.x, y: pos.y + 26 },
            { x: pos.x + 20, y: pos.y },
            { x: pos.x + 100, y: pos.y },
            { x: pos.x + 20, y: pos.y + 52 },
            { x: pos.x + 100, y: pos.y + 52 },
        ];
    }

    pickClosestPort(ports, target) {
        if (!ports.length) {
            return null;
        }
        let best = ports[0];
        let bestDist = (best.x - target.x) ** 2 + (best.y - target.y) ** 2;
        for (const port of ports) {
            const dist = (port.x - target.x) ** 2 + (port.y - target.y) ** 2;
            if (dist < bestDist) {
                best = port;
                bestDist = dist;
            }
        }
        return best;
    }

    getSvgPoint(ev) {
        const svg = this.svgRef.el;
        if (!svg || !svg.getScreenCTM) {
            return { x: 0, y: 0 };
        }
        const point = svg.createSVGPoint();
        point.x = ev.clientX;
        point.y = ev.clientY;
        const ctm = svg.getScreenCTM();
        if (!ctm) {
            return { x: 0, y: 0 };
        }
        const cursor = point.matrixTransform(ctm.inverse());
        return { x: cursor.x, y: cursor.y };
    }

    onNodePointerDown(ev) {
        const stateId = parseInt(ev.currentTarget?.dataset?.stateId || "0", 10);
        if (!stateId) {
            return;
        }
        if (this.state.linkMode) {
            if (!this.state.linkSourceId) {
                this.state.linkSourceId = stateId;
                this.state.selectedStateId = stateId;
                this.notification.add("Select destination state", { type: "info" });
                return;
            }
            if (this.state.linkSourceId === stateId) {
                this.state.linkMode = false;
                this.state.linkSourceId = null;
                this.selectState(stateId);
                this.notification.add("Link canceled", { type: "warning" });
                return;
            }
            this.createTransition(this.state.linkSourceId, stateId);
            this.state.linkMode = false;
            this.state.linkSourceId = null;
            return;
        }
        this.selectState(stateId);
        ev.preventDefault();
        ev.stopPropagation();
        const pos = this.state.positions[stateId];
        if (!pos) {
            return;
        }
        const cursor = this.getSvgPoint(ev);
        this.state.draggingId = stateId;
        this.state.dragOffset = { x: cursor.x - pos.x, y: cursor.y - pos.y };
        if (ev.target.setPointerCapture) {
            ev.target.setPointerCapture(ev.pointerId);
        }
    }

    async createTransition(sourceId, destId) {
        const versionId = this.state.selectedVersionId;
        if (!versionId) {
            return;
        }
        const sourceState = this.getStateById(sourceId);
        const isCondition = sourceState?.type === "condition";
        const [transitionId] = await this.orm.create("workflow.transition", [{
            name: isCondition ? "Branch" : "Transition",
            version_id: versionId,
            source_state_id: sourceId,
            dest_state_id: destId,
            trigger: isCondition ? "auto" : "manual",
            transition_type: "normal",
            branch_expression: isCondition ? "True" : false,
            branch_is_else: false,
        }]);
        this.notification.add(isCondition ? "Branch created" : "Transition created", { type: "success" });
        await this.loadGraph(versionId);
        await this.selectTransition(transitionId);
    }

    onEdgeClick(ev) {
        const transitionId = parseInt(ev.currentTarget?.dataset?.transitionId || "0", 10);
        if (!transitionId) {
            return;
        }
        this.selectTransition(transitionId);
    }

    onCanvasPointerDown(ev) {
        if (ev.button !== 0) {
            return;
        }
        if (ev.target.closest(".we-node")) {
            return;
        }
        this.state.panning = true;
        this.state.panStart = { x: ev.clientX, y: ev.clientY };
        this.state.panOrigin = { ...this.state.pan };
    }

    onCanvasPointerMove(ev) {
        if (!this.state.draggingId && this.state.panning) {
            const dx = ev.clientX - this.state.panStart.x;
            const dy = ev.clientY - this.state.panStart.y;
            this.state.pan = {
                x: this.state.panOrigin.x + dx,
                y: this.state.panOrigin.y + dy,
            };
            return;
        }
        if (!this.state.draggingId) {
            return;
        }
        const cursor = this.getSvgPoint(ev);
        const stateId = this.state.draggingId;
        this.state.positions[stateId] = {
            x: cursor.x - this.state.dragOffset.x,
            y: cursor.y - this.state.dragOffset.y,
        };
    }

    onCanvasPointerMove(ev) {
        if (!this.state.draggingId) {
            return;
        }
        const cursor = this.getSvgPoint(ev);
        const stateId = this.state.draggingId;
        this.state.positions[stateId] = {
            x: cursor.x - this.state.dragOffset.x,
            y: cursor.y - this.state.dragOffset.y,
        };
    }

    async onCanvasPointerUp() {
        if (this.state.panning) {
            this.state.panning = false;
            return;
        }
        const stateId = this.state.draggingId;
        if (!stateId) {
            return;
        }
        this.state.draggingId = null;
        const pos = this.snapToGrid(this.state.positions[stateId]);
        this.state.positions[stateId] = pos;
        await this.orm.write("workflow.state", [stateId], { ui_x: pos.x, ui_y: pos.y });
        this.notification.add("Position saved", { type: "success" });
    }

    async deleteSelectedState() {
        const stateId = this.state.selectedStateId;
        if (!stateId) {
            return;
        }
        if (!window.confirm("Delete this state?")) {
            return;
        }
        await this.orm.unlink("workflow.state", [stateId]);
        this.state.selectedStateId = null;
        await this.loadGraph(this.state.selectedVersionId);
    }

    async deleteSelectedTransition() {
        const transitionId = this.state.selectedTransitionId;
        if (!transitionId) {
            return;
        }
        if (!window.confirm("Delete this transition?")) {
            return;
        }
        await this.orm.unlink("workflow.transition", [transitionId]);
        this.state.selectedTransitionId = null;
        this.state.selectedTransitionSourceType = null;
        await this.loadGraph(this.state.selectedVersionId);
    }
}

WorkflowDesigner.template = "workflow_engine.WorkflowDesigner";

registry.category("actions").add("workflow_engine.designer", WorkflowDesigner);
