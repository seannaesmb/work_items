# Ansible: Find processes on Windows hosts using Cygwin (ps) with fallbacks

This small Ansible playbook tries to run Cygwin's `ps -ef` on Windows hosts by locating a `bash.exe` install path and invoking it. If Cygwin is not available, it falls back to PowerShell's `Get-Process` (JSON) and finally to `tasklist /FO CSV`.

Files
- `ansible_cygwin_find_processes.yml` - the playbook to run against `hosts: windows`.

How it works
- Checks common Cygwin `bash.exe` locations using `win_stat`.
- If a `bash.exe` is found, runs: `"C:\\path\\to\\bash.exe" -lc "ps -ef"` and returns stdout lines.
- Otherwise runs a PowerShell `Get-Process` command and parses JSON.
- If PowerShell output is unavailable, runs `tasklist /V /FO CSV` as a last resort.

Usage
- Ensure your Ansible inventory has a `windows` host/group reachable via WinRM.
- Run the playbook:

```bash
ansible-playbook -i inventory.ini ansible_cygwin_find_processes.yml
```

Troubleshooting
- WinRM connectivity: ensure WinRM is configured on target Windows hosts.
- Permissions: The account used by Ansible must be allowed to call bash.exe and list processes.
- Cygwin path: If you have a non-standard Cygwin install, add the path to the `bash_paths` var at the top of the playbook.
- Encoding: Cygwin output may contain Unix line endings; Ansible normalizes stdout.

Notes
- The playbook intentionally uses `failed_when: false` and `changed_when: false` for the read-only commands so it doesn't mark hosts as failed if a single method isn't available.
- You can extend the PowerShell block to include more fields if you need CPU/Memory details.

Examples: parsing tasklist CSV in Ansible

If the playbook returns `tasklist /FO CSV`, you can parse those CSV lines in Ansible using a small set_fact and a filter. Example task snippet:

```yaml
- name: Parse tasklist CSV lines
	set_fact:
		tasks_parsed: >-
			{{ tasklist_csv.stdout_lines[1:] | map('from_csv')
				 | map('zip', tasklist_csv.stdout_lines[0] | from_csv)
				 | map('items2dict') | list }}

# items2dict is a small custom filter you can add if needed. Alternatively parse in Jinja.
```

Example: using PowerShell JSON output

The playbook already runs `Get-Process | ConvertTo-Json`. To access these in a later task:

```yaml
- name: Save processes into fact
	set_fact:
		processes: "{{ ps_json.stdout | from_json }}"

- name: Show first process name
	debug:
		msg: "First: {{ processes[0].Name }}"
	when: processes is defined and processes | length > 0
```

Common issues and fixes
- If you see "bash.exe not found": add your path to `bash_paths` or install Cygwin.
- If WinRM fails: test connectivity with `ansible -m win_ping windows` and verify the WinRM service on the host.
- If output seems truncated: consider increasing WinRM MaxMemoryPerShellMB or use PowerShell JSON which avoids truncation.
