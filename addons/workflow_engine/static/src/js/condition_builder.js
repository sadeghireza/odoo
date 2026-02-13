/** @odoo-module **/

function buildLiteral(value, fieldType) {
    if (fieldType === "boolean") {
        return value === "true" || value === "1" || value === true ? "True" : "False";
    }
    if (fieldType === "integer" || fieldType === "float" || fieldType === "monetary") {
        const numberValue = parseFloat(value || "0");
        return Number.isNaN(numberValue) ? "0" : numberValue.toString();
    }
    if (fieldType === "many2one" || fieldType === "many2many" || fieldType === "one2many") {
        const numberValue = parseInt(value || "0", 10);
        return Number.isNaN(numberValue) ? "0" : numberValue.toString();
    }
    return JSON.stringify(value || "");
}

function buildListLiteral(value, fieldType) {
    const parts = (value || "").split(",").map((item) => item.trim()).filter(Boolean);
    if (!parts.length) {
        return "[]";
    }
    if (fieldType === "integer" || fieldType === "float" || fieldType === "monetary" || fieldType === "many2one") {
        return `[${parts.map((p) => buildLiteral(p, fieldType)).join(", ")}]`;
    }
    return `[${parts.map((p) => buildLiteral(p, "char")).join(", ")}]`;
}

function buildRuleExpression(rule, info) {
    const fieldExpr = `record.${rule.field}`;
    const operator = rule.operator === "=" ? "==" : rule.operator;
    const value = rule.value;
    if (operator === "is_set") {
        return `bool(${fieldExpr})`;
    }
    if (operator === "is_not_set") {
        return `not ${fieldExpr}`;
    }
    if (operator === "contains") {
        if (info.type === "many2many" || info.type === "one2many") {
            const literal = buildLiteral(value, "number");
            return `${literal} in ${fieldExpr}.ids`;
        }
        const literal = buildLiteral(value, info.type);
        return `${literal} in (${fieldExpr} or '')`;
    }
    if (operator === "in" || operator === "not_in") {
        const listLiteral = buildListLiteral(value, info.type);
        return `${fieldExpr} ${operator === "in" ? "in" : "not in"} ${listLiteral}`;
    }
    const literal = buildLiteral(value, info.type);
    if (info.type === "many2one") {
        return `${fieldExpr}.id ${operator} ${literal}`;
    }
    if (info.type === "many2many" || info.type === "one2many") {
        return `${literal} ${operator === "!=" ? "not in" : "in"} ${fieldExpr}.ids`;
    }
    return `${fieldExpr} ${operator} ${literal}`;
}

export function buildExpressionFromRules(rules, fieldMap) {
    const filtered = rules.filter((r) => r.field && r.operator);
    if (!filtered.length) {
        return "True";
    }
    const parts = [];
    for (let i = 0; i < filtered.length; i += 1) {
        const rule = filtered[i];
        const info = fieldMap[rule.field] || { type: "char" };
        const expr = buildRuleExpression(rule, info);
        if (!expr) {
            continue;
        }
        if (i > 0) {
            parts.push(rule.logic || "and");
        }
        parts.push(`(${expr})`);
    }
    return parts.join(" ") || "True";
}

export function parseExpressionToRules(expression) {
    if (!expression) {
        return [{ field: "", operator: "=", value: "", logic: "and" }];
    }
    const cleaned = expression.replace(/\(|\)/g, " ");
    const tokens = cleaned.split(/\s+(and|or)\s+/i).filter((t) => t && t.trim());
    const rules = [];
    let logic = "and";
    for (let i = 0; i < tokens.length; i += 1) {
        const token = tokens[i].trim();
        if (token.toLowerCase() === "and" || token.toLowerCase() === "or") {
            logic = token.toLowerCase();
            continue;
        }
        const match = token.match(/record\.([a-zA-Z0-9_\.]+)\s*(==|=|!=|>=|<=|>|<|in|not in)\s*(.+)/);
        if (!match) {
            continue;
        }
        const field = match[1].split(".")[0];
        const operator = match[2] === "==" ? "=" : match[2];
        const value = match[3].replace(/^\s+|\s+$/g, "");
        rules.push({ field, operator, value: value.replace(/^['\"]|['\"]$/g, ""), logic });
        logic = "and";
    }
    return rules.length ? rules : [{ field: "", operator: "=", value: "", logic: "and" }];
}
