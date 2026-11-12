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
pip install mcta          # plotting tools only
pip install mcta[seeker]  # + mt.seeker (pymatgen, mp-api, openai); also enables mt.skl
pip install mcta[skl]     # + mt.skl (scikit-learn, joblib)
pip install mcta[sqs]     # + mt.sqs (sqsgenerator)
pip install mcta[mc]      # + mt.mc (numba)
pip install mcta[all]     # all: seeker + skl + sqs + mc
```
Every extra is optional; only the tools that need one ask for it (`mt.seeker` &rarr; `mcta[seeker]`, `mt.skl` &rarr; `mcta[skl]`, `mt.sqs` &rarr; `mcta[sqs]`, `mt.mc` &rarr; `mcta[mc]`).
***
<b style="color:blue;"><i>mt</b></i> prints an overview, checks the current directory and suggests the next command.
***
<b style="color:blue;"><i>mt.band</b></i>: VASP band structures, with optional `vaspkit` data
* `-i` selects a directory (default: current); VASP output is preferred, otherwise `BAND.dat` / `PBAND*.dat` / `PDOS*.dat` are used. `-d` adds DOS, `-r -p Mo-d` adds projections, and `-D -d` makes a spin-polarized mirror plot.
* `-m` calculates effective masses; two or three directories compare calculations; `-l` sets k-path labels and `--export-dat DIR` exports vaspkit-style data.
* Energies are shifted to the Fermi level (`--no-shift` disables this); k-path labels come from `KPOINTS` / `KLABELS` or are computed automatically.
* For combined SCF-mesh/band-path calculations, only zero-weight path points are plotted; `--keep-weights` keeps every k point. vaspkit `.dat` files are used unchanged.
```bash
mt.band                         # bands of the current directory
mt.band -i calc_PBE -d -z       # bands + DOS (DOSCAR or PDOS*.dat)
mt.band -i calc_PBE -r -p Mo-d  # projected bands from PROCAR
mt.band -i calc_PBE -D -d       # spin-polarized bands + mirror DOS
mt.band -i calc_PBE -m 0.15     # effective masses from EIGENVAL
mt.band -i calc_PBE calc_HSE    # compare calculations
```
***
<b style="color:blue;"><i>mt.dos</b></i>: DOS / PDOS as a standalone figure, energy on the horizontal axis
* Reads `DOSCAR` (needs `LORBIT = 11`) or vaspkit `PDOS*.dat` / `TDOS*.dat`; `-i` takes a directory or `.dat` files, defaulting to the current directory.
* `-n` exchanges the axes to match the `mt.band -d` panel; `--no-mirror` keeps the spin-down DOS positive.
* `-p` picks projections, `-e` renames the legend, `-x` sets the DOS range, `-y` the energy window, and `-z` fills the curves.
```bash
mt.dos -i calc                 # DOS from DOSCAR / PDOS*.dat (energy on x)
mt.dos -i calc -p d -x 0 30    # d-orbital PDOS with a fixed DOS range
mt.dos -i calc -o PDOS.png -z  # filled curves
mt.dos -i calc -n              # energy vertical (mt.band -d orientation)
```
***
<b style="color:blue;"><i>mt.phband</i></b>: phonon band structure with an optional DOS panel
* `-i` takes `BAND.dat` written by `phonopy-bandplot --gnuplot`; `-l` labels high-symmetry points and `-y` sets the frequency window.
* `-d [FILE]` adds a DOS panel sharing the frequency axis (`projected_dos.dat` / `total_dos.dat` auto-detected); use `mt.phdos` for a standalone DOS figure.
* `-B start end` breaks the axis for optical branches; two or three files are compared side by side.
```bash
mt.phband -h                                # all parameters
mt.phband -i BAND.dat -o BAND.png -l g m k g -d projected_dos.dat -z
mt.phband -B 23 100 -l g m k g -y -2 110    # broken axis
mt.phband -i BAND1.dat BAND2.dat -B 20 100  # several files
```
***
<b style="color:blue;"><i>mt.phdos</b></i>: phonon DOS as a standalone figure, frequency on the horizontal axis
* Reads `projected_dos.dat` or `total_dos.dat`; `-i` takes a directory or `.dat` file, defaulting to the current directory.
* `-n` exchanges the axes to match the `mt.phband -d` panel.
* `-e` renames the legend, `-x` sets the DOS range, `-y` the frequency window, and `-z` fills the curves.
```bash
mt.phdos                   # DOS of the current directory
mt.phdos -i calc -z        # filled curves
mt.phdos -i calc -x 0 0.6  # fix the DOS range
mt.phdos -i calc -n        # frequency vertical (mt.phband -d orientation)
```
***
<b style="color:blue;"><i>mt.ph</b></i>: phonopy workflow helper
* The default interactive workflow covers supercell &rarr; force constants &rarr; band &rarr; DOS; `-b -d` writes `band.conf` + `mesh.conf`, `-Y` skips confirmation, and `-R` only prints commands.
* The unit cell is auto-detected (`POSCAR-unitcell` &rarr; `CONTCAR` &rarr; `POSCAR`) or set with `-c`; commands adapt to phonopy v3/v4.
* `fs` collects force data: one `vasprun.xml` uses `--fc`, while several files or displacement directories use `--sp -f`; sources come from names, `-n`, or `-x`.
* Additional steps include `band`, `dos`, `tprop`, `born`, `symmetry`, `qha`, and `gruneisen`; see `mt.ph -h` for all options.
* `w` / `W` queries the offline English/Chinese wordbook; `w c` lists setting tags, `--path` shows its location, and `MT_PH_DOCS` selects a custom JSON file.
```bash
mt.ph                      # interactive workflow (default: supercell)
mt.ph -b -d                # write band.conf + mesh.conf
mt.ph fs 001-003           # collect forces from displacement directories
mt.ph band                 # band.conf -> band.yaml -> BAND.dat
mt.ph dos --total          # mesh.conf -> projected_dos.dat + total_dos.dat
mt.ph w --dim BAND_LABELS  # English original, then Chinese translation
```
***
<b style="color:blue;"><i>mt.ph3</b></i>: phono3py lattice thermal-conductivity workflow
* Guides supercell generation, force collection, and thermal-conductivity calculations, with commands adapted to phono3py v3/v4; `-Y` skips confirmation and `-R` only prints commands.
* `-s` / `-S` set FC3 / FC2 supercell dimensions, `-c` sets the unit cell, and `--rd` creates random-direction displacements.
* `cf3` / `cf2` collect forces, while `cfs` and `fs2f2` convert force-set formats; `--sp` writes `phono3py_params.yaml`.
* `kappa` runs RTA by default (`--lbte` for direct LBTE); `kaccum` writes cumulative conductivity, `kdeplot` shows lifetime distributions, and `w` / `W` queries the offline wordbook.
```bash
mt.ph3 supercell -s 2 2 2 -S 4 4 4   # separate FC3 and FC2 supercells
mt.ph3 cf3 -n disp-{00001..00755}    # displacement forces -> FORCES_FC3
mt.ph3 kappa -m 11 11 11             # RTA -> kappa-m111111.hdf5
mt.ph3 kappa -m 11 11 11 --lbte      # direct LBTE solution
mt.ph3 kaccum -k kappa-m111111.hdf5  # cumulative conductivity -> kaccum.dat
mt.ph3 w --br --symfc                # English original, then Chinese translation
```
***
<b style="color:blue;"><i>mt.seeker</b></i>: Materials Project retrieval and curation
Retrieves structures, writes CIF / POSCAR / JSON bundles with optional calculation templates, and filters or deduplicates local datasets; no calculations run locally. Set the API key once (free account at https://next-gen.materialsproject.org), then run searches or curation:
```bash
mkdir -p ~/.config/mcta
echo 'MP_API_KEY=your-key' >> ~/.config/mcta/config
chmod 600 ~/.config/mcta/config
mt.seeker -c Ti-C -k 3 -n ti-c        # search by chemical system, export top 3
mt.seeker -f MoS2 -k 5 -F cif,poscar  # search by formula
mt.seeker -r -D 8 -o my-pick          # deduplicate + pick 8 diverse structures
```
Bundles land in `exports/<name>/` plus `exports/<name>.tar.gz`; `-I` accepts MP IDs, `-t` accepts natural-language tasks, and `-T` downloads more structures.
`mt.seeker -h` lists all options, LLM engines, and `MT_SEEKER_*` environment variables; short options are case-sensitive.
***
<b style="color:blue;"><i>mt.sqs</b></i>: special quasirandom structures from a custom unit cell
Reads POSCAR / CONTCAR / CIF / JSON, expands a supercell, and randomises one sublattice toward a target composition using `sqsgenerator`; no network access is required.
```bash
mt.sqs -c cell.vasp -a "Cu:0.5,Au:0.5" -x 4,4,4 -n cuau-sqs
mt.sqs -c LaAlO3.cif --host La -a "La:0.5,Sr:0.5" -x 2,2,2    # A-site only
mt.sqs -c cell.vasp -a Cu,Au --iterations 1000 --number 5 -R  # dry-run: no disk write
```
Bundles contain `sqs.json` and `sqs_summary.csv`; `mt.sqs -h` lists every flag and default.
***
<b style="color:blue;"><i>mt.mc</b></i>: Monte Carlo simulation of phase transitions in 2D/3D magnetic materials
* Runs the Metropolis Ising model on square, triangular, and bilayer lattices, writing magnetization, susceptibility, and specific heat per temperature to a `.log` file.
* `-x/-y/-z` set lattice size, `-e/-w` set equilibration/sampling sweeps, `-p/-j/-k` set couplings, `-a` sets anisotropy, and `-i` selects the initial state; `--chain`, `--swaps`, and `--seeds` control parallel chains, replica exchange, and reproducibility.
* `-t` accepts a count (`35`), a range (`20 25`), start/stop/step (`20 26 2`), separate temperatures (`20 25 30`), or chained ranges.
* Requires `numba` (`pip install "mcta[mc]"`); plots are automatic unless `-R` is given, and `-o FILE -f pdf` re-plots a finished run.
```bash
mt.mc -x 128 -y 128 -t 0 40 2 --chain 6 --seeds 42   # 6 parallel chains, reproducible
mt.mc -x 64 -y 64 -t 20 40 2 --swaps 20 --seeds 42   # replica exchange
mt.mc -c triangular -t 0 60 2 --seeds 42             # triangular lattice
mt.mc -c bilayer-ab -t 0 60 2 --swaps 20 --seeds 42  # bilayer + replica exchange
mt.mc -c square -a 0.1 -t 20 40 2 --seeds 42         # vector spins with anisotropy
mt.mc -o square_Ising_64_64.log -f pdf               # re-plot a finished run
```
***
<b style="color:blue;"><i>mt.sh</b></i>: run bash helper scripts by short name
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

## Citation

Structure data comes from the Materials Project: A. Jain et al., *APL Materials* 1, 011002 (2013).
