# Workflow Engine Usage Guide (English)

## Overview
The Workflow Engine module provides a model-agnostic, data-driven workflow runtime with versioned process definitions, approvals, SLA timers, delegation, and audit trails. This guide explains how to define a process and run it against any model record.

## Installation
1. Install the module `workflow_engine` from Apps.
2. Ensure the cron job "Workflow SLA Escalation" is active.
3. Assign users to the groups:
   - Workflow Admin
   - Workflow Operator
   - Workflow Auditor (optional)

## Core Concepts
- Process: A top-level workflow definition.
- Version: A frozen set of states and transitions.
- State: A node in the process (start, task, end).
- Transition: A link between states with conditions.
- Role Rule: How assignees are resolved (user, group, dynamic).
- Instance: A runtime workflow for a specific record.
- Work Item: A task assigned to a user for approval.
- SLA Timer: A deadline attached to a state.
- Audit Log: Immutable record of all actions.

## Define a Process (Quick Steps)
1. Create a Process (code must be unique).
2. Create a Version and set its state to "Active".
3. Add States (one start, one or more tasks, optional end).
4. Add Transitions between states.
5. Add Role Rules for approval states.
6. (Optional) Add Conditions and SLA rules.

## Start a Workflow for a Record
In your model, inherit `workflow.mixin` and return a process code.

```python
class MyModel(models.Model):
    _name = "my.model"
    _inherit = "workflow.mixin"

    def _workflow_process_code(self):
        return "my_process_code"
```

Then call:
```python
record.action_start_workflow()
```

## Approvals
- Sequential: Work items are activated one by one.
- Parallel: Work items are activated at the same time.
- Users approve/reject their assigned work items.

## SLA
Attach an SLA rule to a state. The SLA service will create timers and escalate on breach.

## Delegation
Create a delegation rule to temporarily route tasks from one user to another.

## REST API (JSON)
Endpoints:
- `/api/workflow/instance/create`
- `/api/workflow/instance/state`
- `/api/workflow/instance/trigger`
- `/api/workflow/instance/audit`
- `/api/workflow/instances`
- `/api/workflow/workitems`
- `/api/workflow/workitems/bulk`

## Example Demo
A demo workflow is included for `workflow.contract.demo` with process code `contract_demo`.

---

# راهنمای استفاده از موتور گردش کار (فارسی)

## معرفی
ماژول موتور گردش کار یک زیرساخت عمومی و داده محور برای تعریف و اجرای فرایندها ارائه می دهد. این ماژول از نسخه بندی فرایند، تایید چند مرحله ای، SLA، واگذاری، و ثبت کامل رویدادها پشتیبانی می کند.

## نصب
1. ماژول `workflow_engine` را نصب کنید.
2. کرون "Workflow SLA Escalation" را فعال نگه دارید.
3. کاربران را به گروه های زیر اختصاص دهید:
   - Workflow Admin
   - Workflow Operator
   - Workflow Auditor (اختیاری)

## مفاهیم اصلی
- فرایند: تعریف کلی گردش کار.
- نسخه: مجموعه ثابت از وضعیت ها و انتقال ها.
- وضعیت: یک گره در فرایند (شروع، کار، پایان).
- انتقال: مسیر بین وضعیت ها با شروط.
- قانون نقش: تعیین مسئولین (کاربر، گروه، پویا).
- نمونه اجرا: اجرای فرایند برای یک رکورد.
- آیتم کاری: کار قابل تایید توسط کاربر.
- SLA: مهلت زمانی برای هر وضعیت.
- گزارش رویداد: ثبت غیر قابل تغییر همه عملیات.

## تعریف فرایند (گام های سریع)
1. یک فرایند ایجاد کنید (کد باید یکتا باشد).
2. یک نسخه ایجاد کنید و حالت آن را "Active" قرار دهید.
3. وضعیت ها را اضافه کنید (یک شروع، چند کار، و در صورت نیاز پایان).
4. انتقال ها را تعریف کنید.
5. برای وضعیت های تایید، قوانین نقش تعیین کنید.
6. (اختیاری) شروط و SLA اضافه کنید.

## شروع گردش کار برای یک رکورد
در مدل خود از `workflow.mixin` ارث بری کنید و کد فرایند را برگردانید.

```python
class MyModel(models.Model):
    _name = "my.model"
    _inherit = "workflow.mixin"

    def _workflow_process_code(self):
        return "my_process_code"
```

سپس اجرا کنید:
```python
record.action_start_workflow()
```

## تاییدها
- ترتیبی: آیتم های کاری به صورت مرحله ای فعال می شوند.
- موازی: آیتم های کاری همزمان فعال می شوند.
- کاربران فقط آیتم های خود را تایید یا رد می کنند.

## SLA
برای هر وضعیت یک قانون SLA تعریف کنید. سرویس SLA تایمر ایجاد می کند و در صورت نقض، escalation انجام می شود.

## واگذاری
برای بازه زمانی مشخص، واگذاری از یک کاربر به کاربر دیگر ثبت کنید.

## REST API (JSON)
مسیرها:
- `/api/workflow/instance/create`
- `/api/workflow/instance/state`
- `/api/workflow/instance/trigger`
- `/api/workflow/instance/audit`
- `/api/workflow/instances`
- `/api/workflow/workitems`
- `/api/workflow/workitems/bulk`

## نمونه
یک نمونه آماده برای مدل `workflow.contract.demo` با کد `contract_demo` قرار داده شده است.
