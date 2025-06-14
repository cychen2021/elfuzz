#!/usr/bin/env python3

import argparse
from collections import OrderedDict, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
import glob
import json
import logging
import os
import re
import shutil
import subprocess
import sys
from typing import BinaryIO
try:
    # Not until 3.11
    from hashlib import file_digest
except ImportError:
    def file_digest(f: BinaryIO):
        import hashlib
        BLOCKSIZE = 65536
        hasher = hashlib.sha256()
        buf = f.read(BLOCKSIZE)
        while len(buf) > 0:
            hasher.update(buf)
            buf = f.read(BLOCKSIZE)
        return hasher

from drive_log import setup_custom_logger
logger = setup_custom_logger('root')

from tqdm import tqdm
from driver import ExceptionInfo, Result, ResultInfo, GenResult

# Global color cycle with ANSI colors
COLOR_GREEN = '\033[92m'
COLOR_RED = '\033[91m'
COLOR_YELLOW = '\033[93m'
COLOR_BLUE = '\033[94m'
COLOR_MAGENTA = '\033[95m'
COLOR_CYAN = '\033[96m'
COLOR_WHITE = '\033[97m'
COLOR_GREY = '\033[90m'
COLOR_END = '\033[0m'
COLOR_CYAN_UNDERLINE = '\033[4;36m'
COLOR_CYCLE = [
    COLOR_GREEN,
    COLOR_RED,
    COLOR_YELLOW,
    COLOR_BLUE,
    COLOR_MAGENTA,
    COLOR_CYAN,
    COLOR_WHITE,
    COLOR_GREY,
    COLOR_CYAN_UNDERLINE,
]

def draw_success_rate(stats, preferred_colors=None):
    BOX = '▓'
    WIDTH = 80

    if preferred_colors is None:
        preferred_colors = {}

    def bar(color, width):
        return f"{color}{BOX*width}{COLOR_END}"

    total = sum(stats.values())
    outcome_bars = []
    legends = []
    color_index = 0

    # Calculate the width for each key and draw the bars
    color_cycle = COLOR_CYCLE[:]
    # Use the preferred colors first
    for key in preferred_colors:
        if key not in stats:
            continue
        color = preferred_colors[key]
        width = int(WIDTH * stats[key] / total)
        outcome_bars.append((key, width, color))
        legends.append(f"{color}{BOX}{COLOR_END} {key}")
        color_cycle.remove(color)
        color_index += 1
    # Then use the color cycle for the rest
    for key, count in stats.items():
        if key in preferred_colors:
            continue
        width = int(WIDTH * count / total)
        color = color_cycle[color_index % len(color_cycle)]
        color_index += 1
        outcome_bars.append((key, width, color))
        legends.append(f"{color}{BOX}{COLOR_END} {key}")

    # Calculate how much width is left after the outcomes are drawn
    used_width = sum(width for _, width, _ in outcome_bars)
    remaining_width = WIDTH - used_width

    # Add any remaining width to the largest outcome
    largest_outcome = max(outcome_bars, key=lambda x: x[1])[0]
    outcome_bars = [(key, width + (remaining_width if key == largest_outcome else 0), color)
                    for key, width, color in outcome_bars]

    # Construct the final drawn bar and legend
    drawn_bar = ''.join(bar(color,width) for _, width, color in outcome_bars)
    legend = ' '.join(legends)

    return drawn_bar + "  " + legend

gentype_re = re.compile(r'var_\d{4}\.(?P<gentype>[a-z]+)\.')
def get_gentype(module_path):
    basename = os.path.basename(module_path)
    # E.g.: var_0000.diffmode.py
    #  => diffmode
    # E.g.: var_0000.complete.py
    #  => complete
    return gentype_re.search(basename).group('gentype')

def generate_stats(logfile):
    color_preferences = {
        'Success': COLOR_GREEN,
        'Error': COLOR_RED,
        'Timeout': COLOR_YELLOW,
        'AFLErr': COLOR_CYAN_UNDERLINE,
    }
    def add_stats(d1, d2):
        return {k: d1.get(k, 0) + d2.get(k, 0) for k in set(d1) | set(d2)}
    # Track stats as we go and print them at the end
    running_stats = defaultdict(lambda: defaultdict(int))
    with open(logfile) as f:
        original_args = json.loads(f.readline())['data']['args']
        for line in f:
            result = json.loads(line)
            try:
                module_path = result['module_path']
            except KeyError:
                print(f"Error: {line}", file=sys.stderr)
            if result['result_type'] == 'ImportError':
                # Mark the batch as an error
                running_stats[get_gentype(module_path)]['ImportError'] += original_args['driver']['num_iterations']
            else:
                running_stats[get_gentype(module_path)][result['result_type']] += 1
    running_stats = { k: dict(v) for k, v in running_stats.items() }
    combined = {}
    for k in running_stats:
        combined = add_stats(combined, running_stats[k])
    print(f"Stats:", file=sys.stderr)
    for k in sorted(running_stats.keys()):
        print(f"  {k}: {running_stats[k]}", file=sys.stderr)
    print(f"  combined: {combined}", file=sys.stderr)
    print(f"Stats (visual):", file=sys.stderr)
    for k in sorted(running_stats.keys()):
        print(f"  {k}: {draw_success_rate(running_stats[k],color_preferences)}", file=sys.stderr)
    print(f"  combined: {draw_success_rate(combined,color_preferences)}", file=sys.stderr)
    total = sum(combined.values())
    success = combined.get('Success', 0)
    print(f"     total: {total} files attempted", file=sys.stderr)
    print(f"   success: {success} files generated", file=sys.stderr)
    if total != 0:
        print(f"  success%: {success/total*100:.2f}%", file=sys.stderr)

def generate_filestats(logfile):
    from idontwannadoresearch.txdm import txdm
    def count_unique_files(outdir, ext):
        try:
            files = glob.glob(os.path.join(outdir, f'*{ext}'))
        except FileNotFoundError:
            return 0
        unique_files = set([
            file_digest(open(os.path.join(outdir, f), 'rb')).hexdigest()
            for f in files
        ])
        return len(unique_files)
    def file_sizes(outdir, ext):
        try:
            return [
                os.path.getsize(os.path.join(outdir, f))
                for f in glob.glob(os.path.join(outdir, f'*{ext}'))
            ]
        except FileNotFoundError:
            return []
    def new_filestats():
        return {
            'file_sizes': {},
            'unique_hashes': {},
        }
    # Tracks file stats for each module, keyed by generation type
    file_stats = defaultdict(lambda: defaultdict(new_filestats))
    with open(logfile) as f:
        original_args = json.loads(f.readline())['data']['args']
        ext = original_args['driver']['output_suffix']
        output_dir = original_args['output_dir']
        for line in f:
            result = json.loads(line)
            module_path = result['module_path']
            generation_type = get_gentype(module_path)
            file_stats[generation_type][module_path]['file_sizes'] = {}
            file_stats[generation_type][module_path]['unique_hashes'] = {}

    # Compute the file stats
    total = sum([
        len(file_stats[generation_type])
        for generation_type in file_stats
    ])
    progress = (tqdm(total=total, desc="Computing file stats", unit="mod")
                if not ON_NSF_ACCESS
                else txdm(total=total, desc="Computing file stats", unit="mod", file=sys.stdout))
    for generation_type in file_stats:
        for module_path in file_stats[generation_type]:
            worker_dir = os.path.join(output_dir, os.path.splitext(os.path.basename(module_path))[0])
            file_stats[generation_type][module_path]['file_sizes'] = file_sizes(worker_dir, ext)
            file_stats[generation_type][module_path]['unique_hashes'] = count_unique_files(worker_dir, ext)
            progress.update()
    progress.close()
    print(f"File stats:", file=sys.stderr)
    computed_file_stats = defaultdict(dict)
    total_unique = 0
    single_unique = 0
    zero_unique = 0
    # Keep both average and n so we compute the combined average correctly
    average_file_size = []
    average_nonzero_file_size = []
    for generation_type in file_stats:
        print(f"  {generation_type}:", file=sys.stderr)
        gen_total_unique = sum([
            file_stats[generation_type][module_path]['unique_hashes']
            for module_path in file_stats[generation_type]
        ])
        total_unique += gen_total_unique
        computed_file_stats[generation_type]['total_unique'] = gen_total_unique
        print(f"    total unique: {gen_total_unique}", file=sys.stderr)
        # Number of generators with just one unique file
        gen_single_unique = len([
            module_path
            for module_path in file_stats[generation_type]
            if file_stats[generation_type][module_path]['unique_hashes'] == 1
        ])
        single_unique += gen_single_unique
        computed_file_stats[generation_type]['single_unique'] = gen_single_unique
        print(f"    single unique: {gen_single_unique}", file=sys.stderr)
        # Number of generators with zero unique files
        gen_zero_unique = len([
            module_path
            for module_path in file_stats[generation_type]
            if file_stats[generation_type][module_path]['unique_hashes'] == 0
        ])
        zero_unique += gen_zero_unique
        computed_file_stats[generation_type]['zero_unique'] = gen_zero_unique
        print(f"    zero unique: {gen_zero_unique}", file=sys.stderr)
        # Average file size
        gen_file_sizes = [
            file_stats[generation_type][module_path]['file_sizes']
            for module_path in file_stats[generation_type]
        ]
        # concatenate all the lists
        gen_file_sizes = sum(gen_file_sizes, [])
        gen_avg_file_size = sum(gen_file_sizes) / len(gen_file_sizes) if len(gen_file_sizes) > 0 else 0
        nonzero_file_sizes = [s for s in gen_file_sizes if s > 0]
        avg_nonzero_file_size = sum(nonzero_file_sizes) / len(nonzero_file_sizes) if len(nonzero_file_sizes) > 0 else 0
        average_file_size.append((gen_avg_file_size, len(gen_file_sizes)))
        average_nonzero_file_size.append((avg_nonzero_file_size, len(nonzero_file_sizes)))
        computed_file_stats[generation_type]['average_file_size'] = gen_avg_file_size
        computed_file_stats[generation_type]['average_nonzero_file_size'] = avg_nonzero_file_size
        print(f"    average file size: {gen_avg_file_size:.2f} bytes", file=sys.stderr)
        print(f"    average nonzero file size: {avg_nonzero_file_size:.2f} bytes", file=sys.stderr)
    # Combined stats
    print(f"  combined:", file=sys.stderr)
    computed_file_stats['combined']['total_unique'] = total_unique
    print(f"    total unique: {total_unique}", file=sys.stderr)
    computed_file_stats['combined']['single_unique'] = single_unique
    print(f"    single unique: {single_unique}", file=sys.stderr)
    computed_file_stats['combined']['zero_unique'] = zero_unique
    print(f"    zero unique: {zero_unique}", file=sys.stderr)
    # Compute the combined average file size
    total_file_size = sum([s*n for s,n in average_file_size])
    total_nonzero_file_size = sum([s*n for s,n in average_nonzero_file_size])
    total_files = sum([n for s,n in average_file_size])
    total_nonzero_files = sum([n for s,n in average_nonzero_file_size])
    combined_avg_file_size = total_file_size / total_files if total_files > 0 else 0
    combined_avg_nonzero_file_size = total_nonzero_file_size / total_nonzero_files if total_nonzero_files > 0 else 0
    computed_file_stats['combined']['average_file_size'] = combined_avg_file_size
    computed_file_stats['combined']['average_nonzero_file_size'] = combined_avg_nonzero_file_size
    print(f"    average file size: {combined_avg_file_size:.2f} bytes", file=sys.stderr)
    print(f"    average nonzero file size: {combined_avg_nonzero_file_size:.2f} bytes", file=sys.stderr)

    # Include the raw file stats in the output
    computed_file_stats['infilled']['raw'] = file_stats['infilled']
    computed_file_stats['complete']['raw'] = file_stats['complete']
    computed_file_stats['diffmode']['raw'] = file_stats['diffmode']

    # Save to a new JSON file based on the output log's name
    output_log = os.path.splitext(logfile)[0]
    output_log += '.filestats.json'
    with open(output_log, 'w') as f:
        json.dump(computed_file_stats, f, indent=2)
    print(f"Wrote file stats to {output_log}", file=sys.stderr)

class filestats_action(argparse.Action):
    def __init__(self, option_strings, dest, **kwargs):
        return super().__init__(option_strings, dest, nargs=0, **kwargs)

    def __call__(self, parser, namespace, values, option_string, **kwargs):
        if namespace.logfile is None:
            parser.error('Must specify --logfile with --stats-only')
        generate_stats(namespace.logfile)
        generate_filestats(namespace.logfile)

        parser.exit()

def generate_corpus(module_path, input_seeds: str, worker_dir, args):
    module_name = os.path.basename(module_path)
    # Copy the module to the output directory
    copied_module_name = os.path.join(worker_dir, module_name)
    shutil.copyfile(module_path, copied_module_name)
    actual_module_name = os.path.join(worker_dir, module_name)
    outdir = os.path.join(worker_dir, "output")
    logfile_name = f'logfile.json'
    actual_logfile_name = os.path.join(worker_dir, logfile_name)
    # if not args.driver.real_feedback:
    cmd = [
        'python', 'driver.py',
        '-n', str(args.driver.num_iterations),
        '-o', outdir,
        '-L', actual_logfile_name,
        '-t', str(args.driver.timeout),
        '-S', str(args.driver.size_limit),
        '-M', str(args.driver.max_mem),
        '-s', args.driver.output_suffix,
        '-i', input_seeds,
        actual_module_name, args.driver.function_name,
    ]
    logger.debug(f"Running: {' '.join(cmd)}")
    input_seed_num = len(input_seeds.split(';'))
    result = None
    try:
        # if not args.driver.real_feedback:
        timeout = 0.5 * args.driver.timeout * input_seed_num * args.driver.num_iterations * 0.5 # Kill the process if 50% of the generation cannot finished in 0.5 timeout
        subprocess.run(cmd, check=True, text=True, timeout=timeout, capture_output=True)
        # else:
        #     subprocess.run(cmd, check=True, text=True, capture_output=True, timeout=210)
    except subprocess.TimeoutExpired as e:
        pass
    except subprocess.CalledProcessError as e:
        result = Result(
            error = ExceptionInfo.from_exception(e, module_path),
            data = ResultInfo(
                time_taken=None,
                memory_used=None,
                stdout=e.stderr,
                stderr=e.stdout,
            ),
            module_path = module_path,
            result_type = GenResult.RunError,
            function_name = args.driver.function_name,
            args = args,
        )
    # Remove the module from the output directory
    try:
        os.remove(copied_module_name)
    except FileNotFoundError:
        pass
    gen_results = []
    try:
        # Read the results from the logfile
        with open(os.path.join(worker_dir, logfile_name)) as f:
            for line in f:
                gen_results.append(json.loads(line))
        # remove the logfile
        os.remove(os.path.join(worker_dir, logfile_name))
    except FileNotFoundError:
        # The logfile wasn't created, so something went wrong
        result = Result(
            error = None,
            data = None,
            module_path = module_path,
            result_type = GenResult.NoLogErr,
            function_name = args.driver.function_name,
            args = args,
        )
    if len(gen_results) == 1 and gen_results[0]['result_type'] == 'ImportError':
        return gen_results

    if len(gen_results) != args.driver.num_iterations:
        if result is None:
            result = Result(
                error = None,
                data = None,
                module_path = module_path,
                result_type = GenResult.UnknownErr,
                function_name = args.driver.function_name,
                args = args,
            )
        # Fill in the remaining entries with the error
        for _ in range(args.driver.num_iterations - len(gen_results)):
            gen_results.append(json.loads(result.json()))
    return gen_results

import util
from typing import Optional
import random

def get_seed_input_dir() -> Optional[str]:
    r = util.get_config('cli.genoutputs.seed_input_dir')
    assert isinstance(r, str) or r is None
    return r

def get_seed_input_samples() -> Optional[int]:
    r = util.get_config('cli.genoutputs.seed_input_samples')
    assert isinstance(r, str) or r is None
    if r is None:
        return None
    return int(r)

def get_resample_iterations() -> int:
    r = util.get_config('cli.genoutputs.resample_iterations')
    assert isinstance(r, str)
    return int(r)

def make_parser():
    parser = argparse.ArgumentParser(
        description='Create outputs using generated programs'
    )
    # Global options
    parser.add_argument(
        '-O', '--output-dir', type=str, default='.',
        help='Output directory')
    parser.add_argument(
        '-j', '--jobs', type=int, default=None,
        help='Maximum number of jobs to run in parallel; None means ncpu',
    )
    parser.add_argument('--raise-errors', action='store_true',
                        help="Don't catch exceptions in the main driver loop")
    parser.add_argument('-L', '--logfile', type=str, default=None,
                        help='Log file for JSON results')
    parser.add_argument('--stats-only', action=filestats_action,
                        default=argparse.SUPPRESS,
                        help='Only compute stats for the given log file')
    # These are passed to every module
    parser.add_argument(
        '-f', '--driver.function_name', type=str,
        help='The function to run in each module',
    )
    from pathlib import Path
    parser.add_argument("--seed_input_dir", type=Path, help="Directory containing seed input files", default=None)
    parser.add_argument("--seed_input_samples", type=int, default=-1, help="Number of samples to take from the whole corpus")
    parser.add_argument("--resample_iterations", type=int, default=-1, help="Number of samples to take from the whole corpus")
    parser.add_argument(
        '-t', '--driver.timeout', type=int, default=2,
        help='Timeout for each function run (in seconds)',
    )
    parser.add_argument(
        '-S', '--driver.size-limit', type=int, default=50*1024*1024,
        help='Maximum size of the output file (in bytes)')
    parser.add_argument(
        '-M', '--driver.max-mem', type=int, default=1024*1024*1024,
        help='Maximum memory usage (in bytes)',
    )
    parser.add_argument(
        '-s', '--driver.output-suffix', type=str, default='.gif',
        help='Suffix for output files',
    )
    parser.add_argument(
        '-g', '--generation', type=str, default='initial',
    )
    parser.add_argument(
        '-n', '--driver.num_iterations', type=int, default=100,
        help='Number of times to run each function in each module (i.e., number of outputs to generate)',
    )
    # parser.add_argument(
    #     '--driver.real_feedback', default=False, action='store_true',
    # )
    return parser

def init_parser(elm):
    elm.subgroup_help['driver'] = 'Options for the generator; will be passed to each module'

def main():
    from idontwannadoresearch.txdm import txdm
    from elmconfig import ELMFuzzConfig
    parser = make_parser()
    config = ELMFuzzConfig(parents={'genoutputs': parser})
    init_parser(config)
    args = config.parse_args()
    logger.setLevel(logging.INFO)

    if args.logfile is not None:
        output_log = open(args.logfile, 'w')
    else:
        output_log = sys.stdout
    
    # Record the arguments we're using in the log
    print(json.dumps(
        {'error': None, 'data': {'args': args.__dict__}},
        default=lambda x: x.__dict__ if hasattr(x, '__dict__') else str(x),
    ), file=output_log)

    # The first line sent by genvariants is the number of modules it will produce
    module_count = int(sys.stdin.readline())
    
    gen: str = args.generation
    resample = get_resample_iterations()

    ELMFUZZ_RUNDIR = os.environ.get('ELMFUZZ_RUNDIR', '.')
    
    assert gen.startswith('gen')
    if resample != -1:
        if int(gen.removeprefix('gen')) % resample == 0:
            print('INFO: Resample seed inputs')
            seed_input_dir = get_seed_input_dir()
            assert seed_input_dir is not None
            seed_inputs_raw = []
            for p, ds, fs in os.walk(seed_input_dir):
                for f in fs:
                    seed_inputs_raw.append(os.path.join(p, f))
            
            seed_input_samples = get_seed_input_samples()
            if seed_input_samples is not None and seed_input_samples != -1:
                input_seeds = random.sample(seed_inputs_raw, seed_input_samples)
            else:
                input_seeds = seed_inputs_raw
        else:
            print('INFO: Inherit seed inputs')
            input_seeds = []
            previous_gen = f'gen{int(gen.removeprefix("gen")) - 1}' if gen.startswith('gen') else 'initial'
            with open(f'{ELMFUZZ_RUNDIR}/{previous_gen}/seed_inputs', 'r') as f:
                for line in f:
                    input_seeds.append(line.strip())
        
        with open(f'{ELMFUZZ_RUNDIR}/{gen}/seed_inputs', 'w') as f:
            for seed in input_seeds:
                print(seed, file=f)
        input_seeds_str = ';'.join(input_seeds)
    else:
        tmp = get_seed_input_samples()
        assert tmp is None or tmp == -1
        seed_inputs_raw = []
        seed_input_dir = get_seed_input_dir()
        assert seed_input_dir is not None
        for p, ds, fs in os.walk(seed_input_dir):
            for f in fs:
                seed_inputs_raw.append(os.path.join(p, f))
        input_seeds_str = ';'.join(seed_inputs_raw)

    # if args.driver.real_feedback:
    #     print('INFO: Using real feedback', file=sys.stderr)

    # Call generate_all on each module in args.module_paths in parallel
    with ProcessPoolExecutor(max_workers=args.jobs) as executor:
        progress = (tqdm(total=module_count, desc="Generating", unit="mod")
                    if ON_NSF_ACCESS
                    else txdm(total=module_count, desc="Generating", unit="mod", file=sys.stdout))
        futures_to_paths = OrderedDict()
        for module_path in sys.stdin:
            module_path = module_path.strip()
            # Make an output directory for this module's outputs
            module_base = os.path.splitext(os.path.basename(module_path))[0]
            worker_dir = os.path.join(args.output_dir, module_base)
            os.makedirs(worker_dir, exist_ok=True)
            future = executor.submit(
                generate_corpus,
                module_path, input_seeds_str, worker_dir, args
            )
            future.add_done_callback(lambda _: progress.update())
            futures_to_paths[future] = (module_path, worker_dir)
        for future in as_completed(futures_to_paths):
            module_path, worker_dir = futures_to_paths[future]
            try:
                result = future.result()
                for res in result:
                    print(json.dumps(res), file=output_log)
            except Exception as e:
                if args.raise_errors: raise
                res = Result(
                    error=ExceptionInfo.from_exception(e, module_path),
                    data = None,
                    module_path = module_path,
                    result_type = GenResult.Error,
                    function_name = args.driver.function_name,
                )
                print(json.dumps({
                    'error': ExceptionInfo.from_exception(e, module_path),
                }), file=output_log)
        progress.close()

    if output_log != sys.stdout:
        output_log.close()

    # Collect statistics if we have a log
    if args.logfile is None: return

    # Print the stats out to stderr now that we're done
    generate_stats(args.logfile)
    # Skip file stats for now, takes too long
    # generate_filestats(args.logfile)

ON_NSF_ACCESS = False

def on_nsf_access() -> dict[str, str] | None:
    if not 'ACCESS_INFO' in os.environ:
        return None
    endpoint = os.environ['ACCESS_INFO']
    return {
        'endpoint': endpoint
    }

if __name__ == '__main__':
    ON_NSF_ACCESS = on_nsf_access() is not None
    
    main()
