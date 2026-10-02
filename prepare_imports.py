#!/usr/bin/env python3
"""Prepare fixed-data DOMjudge imports from the supplied NCPC 2025 archive."""
from pathlib import Path, PurePosixPath
import argparse, hashlib, json, posixpath, re, stat, zipfile

def build(source, destination):
    dest = Path(destination)
    for folder in ['imports', 'prompts', 'reference_solutions']:
        (dest/folder).mkdir(parents=True, exist_ok=True)
    manifest=[]
    with zipfile.ZipFile(source) as original:
        names=set(original.namelist())
        roots=sorted(n[:-len('problem.yaml')] for n in names
                     if n.startswith('ncpc2025-problems/') and n.count('/')==2
                     and n.endswith('/problem.yaml'))
        def read_file(name, root, visited=None):
            visited=set() if visited is None else visited
            if name in visited or not name.startswith(root):
                raise ValueError('Unsafe or cyclic link: '+name)
            visited.add(name)
            info=original.getinfo(name)
            data=original.read(name)
            if stat.S_ISLNK(info.external_attr >> 16):
                target=posixpath.normpath(posixpath.join(posixpath.dirname(name),data.decode()))
                return read_file(target,root,visited)
            return data
        for root in roots:
            slug=PurePosixPath(root).name
            meta=original.read(root+'problem.yaml').decode('utf-8')
            title=re.search(r'^name:\s*(.+)$',meta,re.M).group(1).strip().strip('"')
            statement=original.read(root+'problem_statement/problem.en.tex').decode('utf-8')
            sample_names=sorted(n for n in names if n.startswith(root+'data/sample/') and n.endswith('.in'))
            prompt=f'{title}\nSource: NCPC 2025.\n\nThe following is the original problem statement in LaTeX notation.\nIllustration files are not included in this text-only experiment.\n\n'+statement
            for i,name in enumerate(sample_names,1):
                answer=name[:-3]+'.ans'
                prompt+=f'\n\nSample {i} input:\n```text\n'+read_file(name,root).decode('utf-8').rstrip()+'\n```\n'
                prompt+=f'Sample {i} output:\n```text\n'+read_file(answer,root).decode('utf-8').rstrip()+'\n```\n'
            (dest/'prompts'/f'{slug}.txt').write_text(prompt,encoding='utf-8')
            mappings={}
            for name in sorted(names):
                if not name.startswith(root) or name.endswith('/'): continue
                rel=name[len(root):]
                if rel.startswith('data/') and rel.endswith(('.in','.ans')):
                    bits=rel.split('/')
                    if bits[1] not in ['sample','secret']: continue
                    # DOMjudge imports a flat testcase list. Keep subgroup provenance in names.
                    target='/'.join(bits[:2])+'/'+'__'.join(bits[2:])
                    mappings[target]=name
                elif rel.startswith(('output_validators/','input_validators/','submissions/')):
                    if any(part.startswith('.') for part in PurePosixPath(rel).parts):continue
                    mappings[rel]=name
                elif rel in ['problem.yaml','LICENSE','LICENSE.txt','README','README.md']:
                    mappings[rel]=name
            for target in list(mappings):
                if target.startswith('data/') and target.endswith('.in'):
                    if target[:-3]+'.ans' not in mappings:
                        raise ValueError('Missing answer: '+target)
            ini=f'name = "{title}"\nexternalid = {slug}\nshort-name = {slug}\nallow_submit = 1\nallow_judge = 1\n'
            package=dest/'imports'/f'{slug}.zip'
            resolved_links=0
            with zipfile.ZipFile(package,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as out:
                for target,name in mappings.items():
                    if stat.S_ISLNK(original.getinfo(name).external_attr>>16): resolved_links+=1
                    info=zipfile.ZipInfo(target)
                    info.compress_type=zipfile.ZIP_DEFLATED
                    info.external_attr=(stat.S_IFREG|0o644)<<16
                    out.writestr(info,read_file(name,root))
                out.writestr('domjudge-problem.ini',ini)
                out.writestr('problem.txt',prompt)
                out.writestr('IMPORT-NOTES.txt',
                    'Prepared from the supplied NCPC 2025 archive. Testcase links were resolved; '
                    'nested testcase paths were flattened into names with double underscores. '
                    'Validators and original metadata are preserved. The displayed statement '
                    'uses original LaTeX notation plus public samples; illustrations are omitted. '
                    'No official numeric time or memory limits were supplied; configure and '
                    'verify those with reference solutions before the main experiment.\n')
            accepted=sorted(n for n in names if n.startswith(root+'submissions/accepted/')
                            and n.endswith(('.cpp','.cc','.cxx')))
            reference=None
            if accepted:
                reference=f'reference_solutions/{slug}.cpp'
                (dest/reference).write_bytes(read_file(accepted[0],root))
            manifest.append(dict(slug=slug,name=title,statement=f'prompts/{slug}.txt',
                reference=reference,sample_cases=len(sample_names),
                secret_cases=sum(k.startswith('data/secret/') and k.endswith('.in') for k in mappings),
                custom_validator=bool(re.search(r'^validation:\s*custom',meta,re.M)),
                original_validator_flags=(re.search(r'^validator_flags\s*:\s*(.*)',meta,re.M).group(1)
                    if re.search(r'^validator_flags\s*:',meta,re.M) else None),
                resolved_test_links=resolved_links,import_bytes=package.stat().st_size,
                prompt_sha256=hashlib.sha256(prompt.encode()).hexdigest(),
                time_limit_s=None,memory_limit_mb=None,difficulty=None))
    (dest/'problems.json').write_text(json.dumps(manifest,indent=2,ensure_ascii=False),encoding='utf-8')
    print(f'Prepared {len(manifest)} problems; largest upload {max(p["import_bytes"] for p in manifest)/1e6:.1f} MB.')

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('archive');ap.add_argument('--output',default='.')
    args=ap.parse_args();build(args.archive,args.output)
