/** @odoo-module **/

function buildLiteral(value, fieldType) {
    if (fieldType !== "boolean") {
        return null;
    }
    return value === "true" || value === "True" || value === "1" || value === true ? "True" : "False";
}

function buildRuleExpression(rule, info) {
    const fieldExpr = `record.${rule.field}`;
    const operator = rule.operator === "=" ? "==" : rule.operator;
    const literal = buildLiteral(rule.value, info.type);
    if (!literal) {
        return null;
    }
    if (operator !== "==" && operator !== "!=") {
        return null;
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
        const match = token.match(/record\.([a-zA-Z0-9_]+)\s*(==|=|!=)\s*(True|False)/);
        if (!match) {
            continue;
        }
        const field = match[1];
        const operator = match[2] === "==" ? "=" : match[2];
        const value = match[3].replace(/^\s+|\s+$/g, "");
        rules.push({ field, operator, value, logic });
        logic = "and";
    }
    return rules.length ? rules : [{ field: "", operator: "=", value: "", logic: "and" }];
}
