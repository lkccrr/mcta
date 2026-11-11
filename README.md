[![mcta](https://img.shields.io/pypi/v/mcta?style=flat-square)](https://pypi.org/project/mcta/)
[![mcta](https://img.shields.io/pypi/pyversions/mcta?style=flat-square)](https://pypi.org/project/mcta/)
[![mcta](https://img.shields.io/pypi/l/mcta?style=flat-square)](https://pypi.org/project/mcta/)
[![mcta](https://img.shields.io/pypi/dm/mcta?style=flat-square)](https://pypi.org/project/mcta/)
[![mcta](https://img.shields.io/pypi/wheel/mcta?style=flat-square)](https://pypi.org/project/mcta/)
[![mcta](https://img.shields.io/github/last-commit/lkccrr/mcta?style=flat-square)](https://github.com/lkccrr/mcta)
[![mcta](https://img.shields.io/github/release-date/lkccrr/mcta?style=flat-square)](https://github.com/lkccrr/mcta)

### Meta Crystal Toolkit & Analysis (mcta)

* Install (Python &ge; 3.9; core dependencies: `numpy`, `matplotlib`, `ase`):
```bash
pip install mcta              # plotting tools only
pip install mcta[seeker]      # + mt.seeker (pymatgen, mp-api, openai); also enables mt.skl
pip install mcta[skl]         # + mt.skl (scikit-learn, joblib)
pip install mcta[sqs]         # + mt.sqs (sqsgenerator)
pip install mcta[mc]          # + mt.mc (numba)
pip install mcta[all]         # all : seeker + skl + sqs + mc
```
Every extra is optional: the core install stays small and only the tools that need them ask for one (`mt.seeker` &rarr; `mcta[seeker]`, `mt.skl` &rarr; `mcta[skl]`, `mt.sqs` &rarr; `mcta[sqs]`, `mt.mc` &rarr; `mcta[mc]`).
***
<b style="color:blue;"><i>mt</b></i> prints an overview, checks the current directory and suggests the next command.
***
<b style="color:blue;"><i>mt.band</b></i> — VASP output is the default data source, `vaspkit` is optional
* `-i` takes a directory (default: current). VASP output (`EIGENVAL` / `DOSCAR` / `PROCAR`) is preferred, otherwise `BAND.dat` / `PBAND*.dat` / `PDOS*.dat` are used.
* `-i` alone plots bands, `-i -d` adds the DOS panel on the right sharing the vertical energy axis, `-d` alone plots the DOS only (for a standalone figure with energy on the horizontal axis use `mt.dos`); `-r -p Mo-d` adds projected bands (needs `PROCAR`, `LORBIT = 11`); `-D -d` spin-polarized mirror plot (`--no-mirror` to keep both positive); `-m` effective masses from `EIGENVAL`; two or three directories compare calculations.
* Energies are shifted to the Fermi level (`--no-shift` keeps raw values); k-path labels come from `KPOINTS`/`KLABELS` or are computed automatically; `--export-dat DIR` dumps vaspkit-style `.dat` files.
* Some runs (e.g. HSE hybrids) do the SCF mesh and the band path in one calculation: in `EIGENVAL` / `vasprun.xml` the mesh k points carry a non-zero weight and the path points a weight of 0. Only the zero-weight path points are plotted (the `PROCAR` projections are re-indexed to match), `--keep-weights` keeps every k point. vaspkit `.dat` files are already cleaned, so they are used as they are.
```bash
mt.band                               # bands of the current directory
mt.band -i calc_PBE -l g m k g        # given directory, VASP or .dat auto-detected
mt.band -i calc_PBE -d -z             # bands + DOS (DOSCAR or PDOS*.dat)
mt.band -i calc_PBE -r -p Mo-d        # projected bands from PROCAR
mt.band -i calc_PBE -D -d             # spin polarized: up/down panels + mirror DOS
mt.band -i calc_PBE -m 0.15           # effective masses from EIGENVAL
mt.band -i calc_PBE calc_HSE          # compare calculations
mt.band -i BAND.dat -d PDOS*.dat      # vaspkit .dat route
mt.band -i calc_HSE --keep-weights    # keep the weighted k points as well
```
***
<b style="color:blue;"><i>mt.dos</b></i> — DOS / PDOS as a standalone figure, energy on the horizontal axis
* Same data as `mt.band`: `DOSCAR` (needs `LORBIT = 11`) or vaspkit `PDOS*.dat` / `TDOS*.dat`; `-i` takes a directory or the `.dat` files, default: current directory.
* Default orientation is **energy on the x axis**, DOS on the y axis. `-n` exchanges the axes (energy vertical), which is the orientation used by the `mt.band -d` panel.
* `-p` picks the projections (`s p d`, `Mo-d`, `all`), `-e` renames the legend, `-x` sets the DOS range, `-y` the energy window, `-z` fills the curves, `--no-mirror` keeps the spin-down DOS positive.
```bash
mt.dos -i calc                       # DOS from DOSCAR / PDOS*.dat (energy on x)
mt.dos -i calc -p d -x 0 30          # d-orbital PDOS with a fixed DOS range
mt.dos -i calc -o PDOS.png -z        # filled curves
mt.dos -i calc -n                    # energy vertical (mt.band -d orientation)
```
***
<b style="color:blue;"><i>mt.phband</i></b> — phonon band structure (and the DOS panel next to it)
* `-i` takes `BAND.dat` written by `phonopy-bandplot --gnuplot` (default: `BAND.dat`); `-l` labels the high-symmetry points, `-y` sets the frequency window.
* `-d [FILE]` adds the phonon DOS panel on the right, sharing the vertical frequency axis (`projected_dos.dat` / `total_dos.dat`, auto-detected when no file is given); for a standalone phonon DOS figure with frequency on the horizontal axis use `mt.phdos`.
* `-B start end` breaks the axis for the optical branches; two or three files are compared side by side.
```bash
mt.phband -h                                                    # all parameters
mt.phband -i BAND.dat -o BAND.png -l g m k g -d projected_dos.dat -z
mt.phband -B 23 100 -l g m k g -y -2 110                        # broken axis
mt.phband -i BAND1.dat BAND2.dat -B 20 100                      # several files
```
***
<b style="color:blue;"><i>mt.phdos</b></i> — phonon DOS as a standalone figure, frequency on the horizontal axis
* Reads `projected_dos.dat` or `total_dos.dat` (written by `mt.ph dos`); `-i` takes a directory or the `.dat` file, default: current directory.
* Default orientation is **frequency on the x axis**, DOS on the y axis. `-n` exchanges the axes (frequency vertical), which is the orientation used by the `mt.phband -d` panel.
* `-e` renames the legend, `-x` sets the DOS range, `-y` the frequency window, `-z` fills the curves.
```bash
mt.phdos                             # DOS of the current directory
mt.phdos -i calc -z                  # filled curves
mt.phdos -i calc -x 0 0.6            # fix the DOS range
mt.phdos -i calc -n                  # frequency vertical (mt.phband -d orientation)
```
***
<b style="color:blue;"><i>mt.ph</b></i> — phonopy workflow helper
* `mt.ph -b -d` writes <b style="color:darkred;"><i>band.conf</i></b> + <b style="color:darkred;"><i>mesh.conf</i></b> (names via `-B` / `-D`). Without `-b`/`-d` it walks the phonopy steps one by one (supercell &rarr; force constants &rarr; band &rarr; DOS), printing and confirming each command; `-Y` runs without asking, `-R` only prints. `B` + Enter goes back one level, `Q` + Enter quits.
* The unit cell file is auto-detected (`POSCAR-unitcell` &rarr; `CONTCAR` &rarr; `POSCAR`), or give `-c FILE`.
* The command form is chosen automatically from the installed <b style="color:blue;">phonopy</b> version: v4+ uses `phonopy-init -d --dim=...` / `--sp -f` for setup and `phonopy --config` for post-processing, while v3 uses the legacy `phonopy -d / --fc / -f` options. Band/DOS read `phonopy_params.yaml` (written by `mt.ph fs` with several force files) when present, otherwise `phonopy_disp.yaml` together with `FORCE_CONSTANTS` / `FORCE_SETS`.
* `mt.ph fs` handles all force data: with a **single** `vasprun.xml` (file, or directory holding one) it runs `phonopy-init --fc`; with **several** force files (displacement dirs / suffixes / ranges) it runs `phonopy-init --sp -f`. Sources come from positional `NAME`s, `-n` or `-x` (`-x` alone = the single file, with `-n` = the file name inside each directory). Giving only `-n` or only `-x` implies `fs`.
* Extra subcommands: `mt.ph tprop` (thermal properties &rarr; `thermal_properties.yaml` + `thermal_properties.dat`, no plots), `mt.ph born` (BORN / NAC via `phonopy-vasp-born`), `mt.ph symmetry` (`--symmetry` &rarr; `BPOSCAR` / `PPOSCAR`), `mt.ph qha` (quasi-harmonic approximation, &ge; 5 volume points) and `mt.ph gruneisen` (mode Gr&uuml;neisen parameters, 3 volume points).
* `mt.ph v` / `mt.ph V` looks up phonopy usage in a **local** wordbook shipped with mcta (`mcta/bandplot/phonopy_docs.json`, phonopy commands / options / tags only): with no word it lists all entries; with words (e.g. `mt.ph v --dim BAND_LABELS`) each hit first shows a line with the title and version of the official doc page it was taken from, then the **English original, a blank line, and the Chinese translation**. The English text is verbatim from the phonopy official documentation; lookups are fully offline and never access the network. `mt.ph v --all` prints the whole wordbook, `--path` shows its location, and `MT_PH_DOCS` can point to a custom JSON file.
* `-n` values (for the force-extraction route of `mt.ph fs`, implied by `-n` alone) may be directories, `vasprun.xml` suffixes or brace ranges; `dir-{001..003}` stays compact and bash expands it.
```bash
mt.ph                                           # supercell step (default; -s 2 2 1 sets DIM)
mt.ph -b -d -p "0 0 0 0.5 0 0 0.5 0.5 0.5 0 0 0" -l "G X M G" -N 101 -m "20 20 20"
mt.ph supercell -s 2 2 1 -c POSCAR-unitcell     # explicit supercell
mt.ph fs vasprun.xml                            # one force file -> --fc
mt.ph fs 001-003                                # several -> phonopy-init --sp -f vasprun.xml-{001..003}
mt.ph -x                                        # fs: force constants from ./vasprun.xml
mt.ph -n 001-003                                # fs: phonopy-init --sp -f vasprun.xml-{001..003}
mt.ph band                                      # band.conf -> band.yaml -> BAND.dat
mt.ph dos --total                               # mesh.conf -> projected_dos.dat (+ total_dos.dat)
mt.ph -R supercell -s 2 2 1                     # preview commands for the installed phonopy version
mt.ph tprop -m "31 31 31"                       # thermal_properties.yaml + thermal_properties.dat
mt.ph born                                      # BORN from ./vasprun.xml
mt.ph symmetry -c POSCAR-unitcell               # BPOSCAR / PPOSCAR
mt.ph qha -F e-v.dat thermal_properties.yaml-{00..10} -P
mt.ph gruneisen -G orig plus minus -P           # each dir: POSCAR + FORCE_SETS/FORCE_CONSTANTS
mt.ph v                                         # list the local phonopy wordbook
mt.ph v --dim BAND_LABELS                       # English original, then Chinese translation
mt.ph v --all                                   # print the whole local wordbook
mt.ph V band                                    # same as mt.ph v
```

***
<b style="color:blue;"><i>mt.seeker</b></i> — Materials Project retrieval and curation

Retrieves crystal structures from the **Materials Project**, writes CIF / POSCAR / JSON and packs them into bundles ready for `scp` to a server (with optional INCAR / KPOINTS / slurm templates). Local structures can be filtered, deduplicated and re-exported. No calculations are executed locally. Special quasirandom structures (SQS) from a custom unit cell is handled by the separate `mt.sqs` tool.

Set the API key once (free account at https://next-gen.materialsproject.org):

```bash
mkdir -p ~/.config/mcta
echo 'MP_API_KEY=your-key' >> ~/.config/mcta/config
chmod 600 ~/.config/mcta/config
# or: export MP_API_KEY=...
#(lookup order: env -> $MT_SEEKER_CONFIG -> the file above -> ./mt.seeker.conf)
```

Typical usage:

```bash
mt.seeker --offline                                    # offline self-check, no key needed
mt.seeker -c Ti-C -k 3 -n ti-c                         # search by chemsys, export top 3
mt.seeker -f MoS2 -k 5 -F cif,poscar                   # search by formula
mt.seeker -I mp-149 mp-2658                            # or give mp_ids directly
mt.seeker -c Cr-I -k 2 --job-template                  # + INCAR/KPOINTS/slurm templates
mt.seeker -t "find 2D candidates in Cr-I" -p deepseek  # natural language (needs mcta[seeker])
mt.seeker -L                                           # list previous bundles

# local curation (dedup, filter, diversity, top-up)
mt.seeker -d                                           # dataset summary
mt.seeker -w "ehull<=0.05 and is_2d and has('Mn')"     # rule filter (-R previews only)
mt.seeker -r -D 8 -o my-pick                           # dedup + pick 8 most dissimilar
mt.seeker -T 5 -c Mn-P-S                               # download 5 more structures
```

Each bundle lands in `exports/<name>/` (`structures/<id>/`, `manifest.csv` with 14 columns, `README.md`, `results/`) plus `exports/<name>.tar.gz`. Upload with `scp exports/<name>.tar.gz user@server:~/calc/`.

Short options are case-sensitive: `-t` task vs `-T` top-up, `-r` dedup vs `-R` dry-run; `-Q` refreshes the search cache. `mt.seeker -h` prints the full option list; LLM engines (`-p openai/deepseek/qwen/glm/kimi/siliconflow/gemini/openrouter/ollama/vllm`, any OpenAI-compatible endpoint) and all `MT_SEEKER_*` environment variables are documented there and in the code (`mcta/seeker/config.py`).
***
<b style="color:blue;"><i>mt.sqs</b></i> — special quasirandom structures from a custom unit cell

mt.sqs reads a POSCAR / CONTCAR / CIF / JSON, expands it to a supercell, and randomises a single sublattice into a quasirandom solid solution with a specified target composition (objective: weighted sum of pair-correlation deviations, smaller = closer to perfect randomness). The engine is `sqsgenerator` (C++ + Python), no network access required.

```bash
mt.sqs -c cell.vasp -a "Cu:0.5,Au:0.5" -x 4,4,4 -n cuau-sqs
mt.sqs -c LaAlO3.cif --host La -a "La:0.5,Sr:0.5" -x 2,2,2     # A-site only
mt.sqs -c cell.vasp -a Cu,Au --iterations 1000 --number 5 -R   # dry-run: no disk write
```

SQS bundles additionally contain `sqs.json` and `sqs_summary.csv`. `mt.sqs -h` lists every flag and default. The algorithm lives in `mcta.seeker.sqs`; the rest of `mt.seeker` no longer pulls in sqsgenerator.
***
<b style="color:blue;"><i>mt.mc</b></i> — Monte Carlo simulation of the phase transition in 2D/3D magnetic materials (merged from `spins2`)
* `mt.mc` runs a Metropolis Monte Carlo simulation of the Ising model on square, triangular and bilayer lattices (`-c square|triangular|bilayer-aa|bilayer-ab|bilayer-ab-u-3`) and writes a `.log` file with magnetization, susceptibility and specific heat per temperature.
* `-x/-y/-z` lattice size (default 64&times;64), `-e/-w` equilibration and sampling sweeps (default 1000/1000), `-t` temperature list (default 35), `-p/-j/-k` exchange couplings in meV, `-a` single-ion anisotropy in meV, `-i` initial state (`fm`, `afm1`...`afm5`, `random`), `-N`/`--thrds` number of threads (0 = automatic: about 3/5 of the physical cores), `-C`/`--chain` number of independent chains (0 = same as the thread count), `-W`/`--swaps` replica-exchange interval in sweeps (0 = off), plots are produced by default when the run finishes, `-R`/`--dryrn` skips the plots, `-o FILE` plots an existing `.log`, `-f` image format (any format matplotlib can save, e.g. png/pdf/svg/jpg/tif; a format that cannot be saved prints a warning and falls back to png), `-l` legend.
* `-t` accepts several forms: `-t 35` (0&ndash;34 K), `-t 20 25` (every integer from 20 to 25 K), `-t 20 26 2` (20, 22, 24, 26 K &mdash; start, stop, step) and `-t 20 25 30` (three separate temperatures, used when the step would be larger than the range). Several ranges can be chained: `-t 20 26 2 30 40 2`.
* The kernels are compiled with `numba`, an optional dependency: `pip install "mcta[mc]"`. Without it `mt.mc` prints how to install it and stops; the other `mt` tools are unaffected.
* The default thread count is about 3/5 of the physical cores (4 on a 6-core machine), not the logical core count: filling every core measured slower, because the two hyperthreads of a core share one execution unit and this kernel is memory bound. The threads and the chains share one thread pool, so they never fight over the cores. `--seeds` fixes the random numbers, so the result no longer depends on the thread count.
```bash
mt.mc -h
mt.mc -x 100 -y 100 -e 200 -w 1000 -t 35
mt.mc -x 128 -y 128 -t 0 40 2 --chain 6 --seeds 42       # 6 chains in parallel, reproducible
mt.mc -x 64 -y 64 -t 20 40 2 --swaps 20 --seeds 42        # replica exchange
mt.mc -c triangular -t 0 60 2 --seeds 42                # any configuration, multi-core
mt.mc -c bilayer-ab -t 0 60 2 --swaps 20 --seeds 42      # any configuration, replica exchange
mt.mc -c square -a 0.1 -t 20 40 2 --seeds 42            # vector spins with anisotropy
mt.mc -c square -t 20 25 30 --seeds 42                  # three separate temperatures
mt.mc -o square_Ising_64_64.log -f pdf                 # re-plot a finished run
mt.mc -x 64 -y 64 -t 20 40 2 -R                     # run only, no plots
```
***
<b style="color:blue;"><i>mt.sh</b></i> — run bash helper scripts by short name
* `mt.sh NAME [args...]` executes script `NAME` with bash and forwards the arguments unchanged, e.g. `mt.sh xy POSCAR` runs `xy.sh POSCAR`. The exit code of the script is returned.
* Script lookup order: the current directory (`./NAME.sh`, local overrides first) &rarr; directories listed in `$MTSH_SCRIPTS` (colon/semicolon-separated) &rarr; the scripts bundled with the package (`mcta/sh/scripts/`).
* Bare `mt.sh` lists every bundled script with a one-line description taken from the first comment line.
* Bundled scripts (VASP workflow helpers, best run on Linux/WSL; Windows needs Git Bash on PATH and the scripts use `sed`/`awk`/`bc`):
* Strain scans: `mt.sh x|y|xy [POSCAR] [NPOINTS] [STEP]` rescales the lattice vectors of a POSCAR and writes one directory per strain value. `NPOINTS` is the number of points on **each** side of zero (default 4, so 2&times;N points in total, zero itself excluded) and `STEP` is the strain increment (default 0.01). The result lands in `x/`, `y/` or `xy/`, each holding `<factor>/POSCAR` where `factor = 1 + k*STEP` (`k` from `-N`&hellip;`-1` and `1`&hellip;`N`).
* `kb`: `mt.sh kb [POSCAR] [a [b [c]]] [OUT]` expands the structure `a&times;b&times;c` times with ASE and writes `SPOSCAR` (VASP 5 format, direct coordinates, species sorted). Arguments are read left to right: the first token is the input file unless it is a natural number (then the input defaults to `POSCAR`); up to three natural numbers are the multipliers, missing ones default to 1 (`2` &rarr; 2&times;1&times;1, `2 3` &rarr; 2&times;3&times;1, none &rarr; 1&times;1&times;1); a fourth token after three multipliers is the output file name (default `SPOSCAR`). `POSCAR` may be anything ASE can read (POSCAR, CONTCAR, `*.cif`). The interpreter is resolved automatically: `$PYTHON` if set, otherwise the first `python3` / conda-environment python that can `import ase` (no manual `conda activate` needed); if none works it prints a one-line error instead of a traceback.
* `sy`: `mt.sh sy [POSCAR] [symprec]` reports the symmetry of a structure from `spglib`, with `symprec` defaulting to `1e-3` &Aring; (the angle tolerance is left at the spglib default, which is matched to that tolerance). The second positional argument is the tolerance, e.g. `mt.sh sy POSCAR 1e-2` or `mt.sh sy POSCAR 0.0001`; it must be a positive finite float (`0`, negative values, `nan`, `inf` and non-numeric strings are rejected with a one-line error and exit status 1). Larger tolerances swallow small distortions and tend to give a higher symmetry (fewer inequivalent sites), smaller ones are stricter and tend to give a lower symmetry or even no result. The first positional argument is always a file name (the default `POSCAR` applies only when no argument is given), so `mt.sh sy 0.001` looks for a file called `0.001` and fails; write `mt.sh sy POSCAR 0.001` to change the tolerance of the default structure. It prints the space-group symbol and number, Hall number and symbol, point group and crystal system, the atom counts of the primitive and conventional cells, the `symprec` actually used, then one line per inequivalent Wyckoff site with `multiplicity+letter` (e.g. `4a`), the site symmetry (`m-3m`, `-43m`&hellip;), the element and the equivalent atom indices (1-based). `POSCAR` may be anything ASE can read. Labels follow spglib's standardized cell, so a different origin setting can flip a letter (`8a` vs `8b` for diamond) without changing the multiplicity or site symmetry. Requires `spglib` on top of `ase`: `pip install spglib` (or `conda install -c conda-forge spglib`); the interpreter is resolved exactly as for `kb`, now probing `import ase, spglib`.

```bash
mt.sh x                    # x strain: x/0.960 ... x/1.040 (8 points, step 0.01)
mt.sh y POSCAR 2 0.02      # y strain, 2 points per side, step 0.02
mt.sh xy POSCAR            # x and y strained together
mt.sh kb POSCAR 2 2 1      # POSCAR -> SPOSCAR (2x2x1)
mt.sh sy POSCAR            # space group + Wyckoff sites of POSCAR (symprec 1e-3)
mt.sh sy POSCAR 1e-2       # looser tolerance: distorted structure may look more symmetric
mt.sh sy CONTCAR 0.0001    # tighter tolerance: may drop to a lower symmetry
```

## Citation

Structure data comes from the Materials Project: A. Jain et al., *APL Materials* 1, 011002 (2013).
