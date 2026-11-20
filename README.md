[![mcta](https://img.shields.io/pypi/v/mcta?style=flat-square)](https://pypi.org/project/mcta/)
[![mcta](https://img.shields.io/pypi/pyversions/mcta?style=flat-square)](https://pypi.org/project/mcta/)
[![mcta](https://img.shields.io/pypi/l/mcta?style=flat-square)](https://pypi.org/project/mcta/)
[![mcta](https://img.shields.io/pypi/dm/mcta?style=flat-square)](https://pypi.org/project/mcta/)
[![mcta](https://img.shields.io/pypi/wheel/mcta?style=flat-square)](https://pypi.org/project/mcta/)
[![mcta](https://img.shields.io/github/last-commit/lkccrr/mcta?style=flat-square)](https://github.com/lkccrr/mcta)
[![mcta](https://img.shields.io/github/release-date/lkccrr/mcta?style=flat-square)](https://github.com/lkccrr/mcta)

### Meta Crystal Toolkit & Analysis (McTa)

* Install (Python &ge; 3.9; core dependencies: `numpy`, `matplotlib`, `ase`):
```bash
pip install mcta          # plotting tools only
pip install mcta[seek]    # + mt.seek (pymatgen, mp-api, openai); also enables mt.skl
pip install mcta[skl]     # + mt.skl (scikit-learn, joblib)
pip install mcta[sqs]     # + mt.sqs (sqsgenerator)
pip install mcta[mc]      # + mt.mc (numba)
pip install mcta[all]     # all: seek + skl + sqs + mc
```
Every extra is optional; only the tools that need one ask for it (`mt.seek` &rarr; `mcta[seek]`, `mt.skl` &rarr; `mcta[skl]`, `mt.sqs` &rarr; `mcta[sqs]`, `mt.mc` &rarr; `mcta[mc]`).
***
<b style="color:blue;"><i>mt</i></b> prints an overview, checks the current directory and suggests the next command.
***
<b style="color:blue;"><i>mt.band</i></b> / <b style="color:blue;"><i>mt.phband</i></b>: electronic and phonon band structures, with an optional DOS panel
* `mt.band` reads VASP output from a directory (`-i`, default: current), preferring it over `BAND.dat` / `PBAND*.dat` / `PDOS*.dat`; `-d` adds DOS, `-r -p Mo-d` adds projections, `-D -d` makes a spin-polarized mirror plot, `-m` calculates effective masses, and two or three directories compare calculations.
* Energies are shifted to the Fermi level (`--no-shift` disables this); `-l` sets k-path labels (from `KPOINTS` / `KLABELS` or computed automatically) and `--export-dat DIR` exports vaspkit-style data. For combined SCF-mesh/band-path calculations, only zero-weight path points are plotted (`--keep-weights` keeps every k point); vaspkit `.dat` files are used unchanged.
* `mt.phband` reads `BAND.dat` written by `phonopy-bandplot --gnuplot`; `-l` labels high-symmetry points, `-y` sets the frequency window, `-d [FILE]` adds a DOS panel sharing the axis (`projected_dos.dat` / `total_dos.dat` auto-detected), and `-B start end` breaks the axis for optical branches; two or three files are compared side by side.
```bash
mt.band                         # bands of the current directory
mt.band -i calc_PBE -d -z       # bands + DOS (DOSCAR or PDOS*.dat)
mt.band -i calc_PBE -r -p Mo-d  # projected bands from PROCAR
mt.band -i calc_PBE -D -d       # spin-polarized bands + mirror DOS
mt.band -i calc_PBE -m 0.15     # effective masses from EIGENVAL
mt.band -i calc_PBE calc_HSE    # compare calculations
mt.phband -i BAND.dat -o BAND.png -l g m k g -d projected_dos.dat -z
mt.phband -B 23 100 -l g m k g -y -2 110    # broken axis
mt.phband -i BAND1.dat BAND2.dat -B 20 100  # several files
```
***
<b style="color:blue;"><i>mt.dos</i></b> / <b style="color:blue;"><i>mt.phdos</i></b>: standalone DOS figures for electrons or phonons, energy / frequency on the horizontal axis
* `mt.dos` reads `DOSCAR` (needs `LORBIT = 11`) or vaspkit `PDOS*.dat` / `TDOS*.dat`, from a directory or `.dat` files via `-i`; `-p` picks projections, `-e` renames the legend, `-x` sets the DOS range, `-y` the energy window, and `-z` fills the curves. `-n` exchanges the axes for the `mt.band -d` orientation, and `--no-mirror` keeps the spin-down DOS positive.
* `mt.phdos` reads `projected_dos.dat` / `total_dos.dat`; `-e`, `-x`, `-y` (frequency), `-z` work as above, and `-n` matches the `mt.phband -d` orientation.
```bash
mt.dos -i calc                 # DOS from DOSCAR / PDOS*.dat (energy on x)
mt.dos -i calc -p d -x 0 30    # d-orbital PDOS with a fixed DOS range
mt.dos -i calc -o PDOS.png -z  # filled curves
mt.dos -i calc -n              # energy vertical (mt.band -d orientation)
mt.phdos -i calc -z            # filled curves
mt.phdos -i calc -x 0 0.6      # fix the DOS range
mt.phdos -i calc -n            # frequency vertical (mt.phband -d orientation)
```
***
<b style="color:blue;"><i>mt.ph</i></b> / <b style="color:blue;"><i>mt.ph3</i></b>: phonopy and phono3py workflow helpers
* `mt.ph` runs the interactive supercell &rarr; force constants &rarr; band &rarr; DOS workflow; `-b -d` writes `band.conf` + `mesh.conf`, `-Y` skips confirmation, and `-R` only prints commands. The unit cell is auto-detected (`POSCAR-unitcell` &rarr; `CONTCAR` &rarr; `POSCAR`) or set with `-c`; commands adapt to phonopy v3/v4.
* `mt.ph fs` collects force data (one `vasprun.xml` uses `--fc`, several files or displacement directories use `--sp -f`; sources come from names, `-n`, or `-x`); other steps include `band`, `dos`, `tprop`, `born`, `symmetry`, `qha`, and `gruneisen` (see `mt.ph -h`).
* `mt.ph3` guides supercell generation, force collection, and thermal conductivity, adapting to phono3py v3/v4 with the same `-Y` / `-R`; `-s` / `-S` set FC3 / FC2 supercell dimensions, `-c` the unit cell, and `--rd` creates random-direction displacements. `cf3` / `cf2` collect forces, `cfs` and `fs2f2` convert force-set formats, and `--sp` writes `phono3py_params.yaml`.
* `kappa` runs RTA by default (`--lbte` for direct LBTE), `kaccum` writes cumulative conductivity, and `kdeplot` shows lifetime distributions; `w` / `W` query the offline English/Chinese wordbook (`w c` lists setting tags, `--path` shows its location, `MT_PH_DOCS` selects a custom JSON file).
```bash
mt.ph                      # interactive workflow (default: supercell)
mt.ph -b -d                # write band.conf + mesh.conf
mt.ph fs 001-003           # collect forces from displacement directories
mt.ph w --dim BAND_LABELS  # English original, then Chinese translation
mt.ph3 supercell -s 2 2 2 -S 4 4 4   # separate FC3 and FC2 supercells
mt.ph3 kappa -m 11 11 11             # RTA -> kappa-m111111.hdf5
mt.ph3 kaccum -k kappa-m111111.hdf5  # cumulative conductivity -> kaccum.dat
mt.ph3 w --br --symfc                # English original, then Chinese translation
```
***
<b style="color:blue;"><i>mt.seek</i></b> / <b style="color:blue;"><i>mt.sqs</i></b> / <b style="color:blue;"><i>mt.skl</i></b>: structure retrieval, SQS generation, and data-driven analysis
* `mt.seek`: Materials Project retrieval and curation, run directly on the server. Retrieves structures and writes one export directory `<name>/` in the working root — containing `README.md`, `manifest.csv`, `mt.seek.db` and one `<id>/` directory per structure (CIF / POSCAR / JSON, plus INCAR / KPOINTS / job script when requested; POTCAR is concatenated into the POSCAR directory with `mt.sh po` when a pseudopotential directory is configured). No tarball, no upload; internal cache/state stay hidden in `.mt.seek/`. Also filters or deduplicates local datasets; no calculations run locally. Set the API key once (free account at https://next-gen.materialsproject.org).
* `mt.sqs`: special quasirandom structures from a custom unit cell. Reads POSCAR / CONTCAR / CIF / JSON, expands a supercell, and randomises one sublattice toward a target composition using `sqsgenerator`; no network access is required.
* `mt.skl`: data-driven analysis of exported structures with scikit-learn. Runs two regression tasks (`ehull` stability and `band_gap`) with a random forest and 5-fold cross-validation, writing results to `<home>/ml/`; `--home DIR` sets the working root (default: current directory).
```bash
mkdir -p ~/.config/mcta
echo 'MP_API_KEY=your-key' >> ~/.config/mcta/config
chmod 600 ~/.config/mcta/config
mt.seek -c Ti-C -k 3 -n ti-c        # search by chemical system, export top 3
mt.seek -f MoS2 -k 5 -F cif,poscar  # search by formula
mt.seek -r -D 8 -o my-pick          # deduplicate + pick 8 diverse structures
mt.sqs -c cell.vasp -a "Cu:0.5,Au:0.5" -x 4,4,4 -n cuau-sqs
mt.sqs -c LaAlO3.cif --host La -a "La:0.5,Sr:0.5" -x 2,2,2    # A-site only
mt.sqs -c cell.vasp -a Cu,Au --iterations 1000 --number 5 -R  # dry-run: no disk write
mt.skl                              # analyse <name>/manifest.csv from each export bundle
```
`mt.seek` exports land in `<name>/` directly under the working root (no `exports/`, no `.tar.gz`, no upload): each bundle holds `README.md`, `manifest.csv`, `mt.seek.db`, and one `<id>/` directory per structure containing that id's CIF / POSCAR / JSON (INCAR / KPOINTS / job script are written into the same `<id>/` when requested; POTCAR is generated there by `mt.sh po` only when a pseudopotential directory such as `PBE_PATH` is set and exists). `-I` accepts MP IDs, `-t` accepts natural-language tasks, and `-T` downloads more structures. `mt.sqs` bundles additionally contain `sqs.json` and `sqs_summary.csv`. `mt.seek -h` lists all options, LLM engines, and `MT_SEEK_*` environment variables; short options are case-sensitive; `mt.sqs -h` lists every flag and default.
> Structure data comes from the Materials Project: A. Jain et al., *APL Materials* 1, 011002 (2013).
***
<b style="color:blue;"><i>mt.mc</i></b>: Monte Carlo simulation of phase transitions in 2D/3D magnetic materials
* Runs the Metropolis Ising model on built-in lattices (square, triangular, bilayer, simple-cubic) or any crystal structure (`-s POSCAR -A Fe -D 3.0 3.6 -x 2 -y 2 -z 2`); any of `-a`, `-J`, `-K` switches to the Heisenberg model. Requires `numba` (`pip install mcta[mc]`); ASE is needed for structure mode.
* `-x/-X`, `-y/-Y`, `-z/-Z` set the lattice size or supercell multiplier (default `32`, `-z` ignored for 2D); `-e/-w` set equilibration/sampling sweeps, `-p/-J/-K` couplings, `-a` anisotropy, `-i` initial state, and `-C` / `-W` / `-S` control parallel chains, replica exchange and reproducibility. `-t` accepts a count (`35`), a range (`20 25`), start/stop/step (`20 26 2`), separate temperatures (`20 25 30`), or chained ranges.
* Structure mode (`-s`) reads any ASE-supported file, picks magnetic atoms (`-A Fe,Co` or auto d/f-block), expands the supercell and builds the neighbor table by distance bins (`-D`); `--mom` sets nominal moments (default `2` &rarr; S=±1) and `--ini` the initial state (`fm` / `afm` / `random` or a ±1 list); `-c` is ignored with `-s`. Plots are automatic unless `-R`, and `-o FILE -I pdf` re-plots a finished run.
```bash
mt.mc -x 128 -y 128 -t 0 40 2 -C 6 -S 42   # 6 parallel chains, reproducible
mt.mc -c triangular -t 0 60 2 -S 42        # triangular lattice
mt.mc -c square -a 0.1 -t 20 40 2 -p 5 -J 4 -K 3     # vector spins with anisotropy
mt.mc -s POSCAR -A Fe -D 2.7 3.2 -x 2 -y 2 -z 2 -t 10 30 10 -p 5 2  # from crystal
mt.mc -o square_Ising_32_32.log -I pdf               # re-plot a finished run
```
***
<b style="color:blue;"><i>mt.sh</i></b>: run bash helper scripts by short name
* `mt.sh NAME [args...]` runs `NAME.sh` with bash; local `./NAME.sh` overrides `$MTSH_SCRIPTS`, then bundled scripts. Bare `mt.sh` lists available scripts.
* Strain scans `x|y|xy [POSCAR] [NPOINTS] [STEP]` write `<factor>/POSCAR` under `x/`, `y/`, or `xy/`; defaults are 4 points per side and step 0.01.
* `kb [POSCAR] [a [b [c]]] [OUT]` expands the structure with ASE and writes `SPOSCAR` by default; missing multipliers default to 1.
* `sy [POSCAR] [symprec]` reports spglib space-group and Wyckoff-site information; the default tolerance is `1e-3` &Aring;.
* Bundled VASP helpers target Linux/WSL; on Windows use Git Bash with `sed` / `awk` / `bc` available.
```bash
mt.sh x                  # x strain: x/0.960 ... x/1.040 (8 points, step 0.01)
mt.sh y POSCAR 2 0.02    # y strain, 2 points per side, step 0.02
mt.sh xy POSCAR          # x and y strained together
mt.sh kb POSCAR 2 2 1    # POSCAR -> SPOSCAR (2x2x1)
mt.sh sy POSCAR          # space group + Wyckoff sites (symprec 1e-3)
mt.sh sy CONTCAR 0.0001  # tighter tolerance: may lower the symmetry
```
***
<b style="color:blue;"><i>mt.server</i></b>: local file service, structure viewer and terminal in the browser
* `mt.server [-d PATH] [-p PORT] [-f] [-L HOST] [-S] [-o [PATH]] [--status]`: background on port 9068 by default; `-d` sets the starting directory (defaults to cwd); restarting on the same port replaces the old instance, and the service stops when that terminal closes or exits. `-f` runs it in the terminal (`Ctrl+C` to stop), `-S` stops it, and no log file is written unless `-o` is given (`-o` alone writes `mcta-server-<port>.log`, `-o DIR|FILE` chooses the location, an existing file is overwritten). `--status` lists every port where you have a service running, and `-S --all` stops all of them.
* The tokenized URL (`?t=...`) printed at startup is the only credential — do not share it. `-N` (no token) and `-L` on a non-loopback address are dangerous: each asks you to type `yes` / `YES`, using both asks twice, and `-L 0.0.0.0` prints a warning.
* Runs as the current user with no login: browse, edit and download any accessible file, with a real PTY shell (xterm.js) whose `cd` the file list follows, image previews, and a 3Dmol.js viewer for structures, trajectories and VASP charge-density files (`CHGCAR`, `CHG`, `LOCPOT`, including spin-polarised pairs). The viewer is orthographic by default with a perspective toggle, fixed-angle rotation (Z-axis 45° default), stepped zoom buttons, reset view, 1x-8x PNG/JPEG/WebP export, vertical sliders for isovalue and opacity (live update while dragging), playback for multi-frame trajectories (capped at 300 frames), and automatic CUBE conversion from ASE so that 3Dmol.js handles all formats uniformly.
```bash
mt.server               # background on port 9068; the tokenized URL is printed
mt.server -d ./examples # serve a different directory
mt.server -p 8080       # another port
mt.server -L 0.0.0.0    # listen on all interfaces (asks for yes, then prints a warning)
mt.server -f            # foreground; Ctrl+C to stop
mt.server -N            # no token (asks for yes): open http://127.0.0.1:9068/ directly
mt.server -o run.log    # keep the startup output in run.log (overwritten each start)
mt.server -S            # stop the service on port 9068
mt.server --status      # list every port where mt.server is running
mt.server -S --all      # stop all of them
```
