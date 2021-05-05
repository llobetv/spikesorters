from .hdsort import HDSortSorter
from .klusta import KlustaSorter
from .tridesclous import TridesclousSorter
from .mountainsort4 import Mountainsort4Sorter
from .ironclust import IronClustSorter
from .kilosort import KilosortSorter
from .kilosort2 import Kilosort2Sorter
from .kilosort2_5 import Kilosort2_5Sorter
from .kilosort3 import Kilosort3Sorter
from .spyking_circus import SpykingcircusSorter
from .herdingspikes import HerdingspikesSorter
from .waveclus import WaveClusSorter
from .yass import YassSorter
from .combinato import CombinatoSorter


from .docker_tools import HAVE_DOCKER


sorter_full_list = [
    HDSortSorter,
    KlustaSorter,
    TridesclousSorter,
    Mountainsort4Sorter,
    IronClustSorter,
    KilosortSorter,
    Kilosort2Sorter,
    Kilosort2_5Sorter,
    Kilosort3Sorter,
    SpykingcircusSorter,
    HerdingspikesSorter,
    WaveClusSorter,
    YassSorter,
    CombinatoSorter
]

sorter_dict = {s.sorter_name: s for s in sorter_full_list}

def run_sorter(sorter_name_or_class, recording, output_folder=None, delete_output_folder=False,
               grouping_property=None, use_docker=False, parallel=False, verbose=False, raise_error=True, n_jobs=-1,
               joblib_backend='loky', **params):
    """
    Generic function to run a sorter via function approach.

    Two usages with name or class:

    by name:
       >>> sorting = run_sorter('tridesclous', recording)

    by class:
       >>> sorting = run_sorter(TridesclousSorter, recording)

    Parameters
    ----------
    sorter_name_or_class: str or SorterClass
        The sorter to retrieve default parameters from
    recording: RecordingExtractor
        The recording extractor to be spike sorted
    output_folder: str or Path
        Path to output folder
    delete_output_folder: bool
        If True, output folder is deleted (default False)
    use_docker: bool
        If True and docker backend is installed, spike sorting is run in a docker image
    grouping_property: str
        Splits spike sorting by 'grouping_property' (e.g. 'groups')
    parallel: bool
        If True and spike sorting is by 'grouping_property', spike sorting jobs are launched in parallel
    verbose: bool
        If True, output is verbose
    raise_error: bool
        If True, an error is raised if spike sorting fails (default). If False, the process continues and the error is
        logged in the log file.
    n_jobs: int
        Number of jobs when parallel=True (default=-1)
    joblib_backend: str
        joblib backend when parallel=True (default='loky')
    **params: keyword args
        Spike sorter specific arguments (they can be retrieved with 'get_default_params(sorter_name_or_class)'

    Returns
    -------
    sortingextractor: SortingExtractor
        The spike sorted data

    """
    if use_docker:
        assert HAVE_DOCKER, "To run in docker, install docker on your system and >>> pip install hither docker"

        # we need sorter name here
        if isinstance(sorter_name_or_class, str):
            sorter_name = sorter_name_or_class
        elif sorter_name_or_class in sorter_full_list:
            sorter_name = sorter_name_or_class.sorter_name
        else:
            raise ValueError('Unknown sorter')
        sorting = _run_sorter_hither(sorter_name, recording, output_folder=output_folder,
                                     delete_output_folder=delete_output_folder, grouping_property=grouping_property,
                                     parallel=parallel, verbose=verbose, raise_error=raise_error, n_jobs=n_jobs,
                                     joblib_backend=joblib_backend, **params)
    else:
        sorting = _run_sorter_local(sorter_name_or_class, recording, output_folder=output_folder,
                                    delete_output_folder=delete_output_folder, grouping_property=grouping_property,
                                    parallel=parallel, verbose=verbose, raise_error=raise_error, n_jobs=n_jobs,
                                    joblib_backend=joblib_backend, **params)
    return sorting


if HAVE_DOCKER:
    # conditional definition of hither tools
    import time
    from pathlib import Path
    import hither2 as hither
    import spikeextractors as se
    import numpy as np
    import shutil
    from .docker_tools import modify_input_folder, default_docker_images

    class SpikeSortingDockerHook(hither.RuntimeHook):
        def __init__(self):
            super().__init__()

        def precontainer(self, context: hither.PreContainerContext):
            # this gets run outside the container before the run, and we have a chance to mutate the kwargs,
            # add bind mounts, and set the image
            input_directory = context.kwargs['input_directory']
            output_directory = context.kwargs['output_directory']

            context.add_bind_mount(hither.BindMount(source=input_directory,
                                                    target='/input', read_only=True))
            context.add_bind_mount(hither.BindMount(source=output_directory,
                                                    target='/output', read_only=False))
            context.image = default_docker_images[context.kwargs['sorter_name']]
            context.kwargs['output_directory'] = '/output'
            context.kwargs['input_directory'] = '/input'


    @hither.function('run_sorter_docker_with_container',
                     '0.1.0',
                     image=True,
                     modules=['spikesorters'],
                     runtime_hooks=[SpikeSortingDockerHook()])
    def run_sorter_docker_with_container(
            recording_dict, sorter_name, input_directory, output_directory, **kwargs
    ):
        recording = se.load_extractor_from_dict(recording_dict)
        # run sorter
        kwargs["output_folder"] = f"{output_directory}/working"
        t_start = time.time()
        # set output folder within the container
        sorting = _run_sorter_local(sorter_name, recording, **kwargs)
        t_stop = time.time()
        print(f'{sorter_name} run time {np.round(t_stop - t_start)}s')
        # save sorting to npz
        se.NpzSortingExtractor.write_sorting(sorting, f"{output_directory}/sorting_docker.npz")

    def _run_sorter_hither(sorter_name, recording, output_folder=None, delete_output_folder=False,
                           grouping_property=None, parallel=False, verbose=False, raise_error=True,
                           n_jobs=-1, joblib_backend='loky', **params):
        assert recording.is_dumpable, "Cannot run not dumpable recordings in docker"
        if output_folder is None:
            output_folder = sorter_name + '_output'
        output_folder = Path(output_folder).absolute()
        output_folder.mkdir(exist_ok=True, parents=True)

        with hither.Config(use_container=True, show_console=True):
            dump_dict_container, input_directory = modify_input_folder(recording.dump_to_dict(), '/input')
            kwargs = dict(recording_dict=dump_dict_container,
                          sorter_name=sorter_name,
                          output_folder=str(output_folder),
                          delete_output_folder=False,
                          grouping_property=grouping_property, parallel=parallel,
                          verbose=verbose, raise_error=raise_error, n_jobs=n_jobs,
                          joblib_backend=joblib_backend)

            kwargs.update(params)
            kwargs.update({'input_directory': str(input_directory), 'output_directory': str(output_folder)})
            sorting_job = hither.Job(run_sorter_docker_with_container, kwargs)
            sorting_job.wait()
        sorting = se.NpzSortingExtractor(output_folder / "sorting_docker.npz")
        if delete_output_folder:
            shutil.rmtree(output_folder)
        return sorting
else:
    def _run_sorter_hither(sorter_name, recording, output_folder=None, delete_output_folder=False,
                           grouping_property=None, parallel=False, verbose=False, raise_error=True,
                           n_jobs=-1, joblib_backend='loky', **params):
        raise NotImplementedError


# generic launcher via function approach
def _run_sorter_local(sorter_name_or_class, recording, output_folder=None, delete_output_folder=False,
                      grouping_property=None, parallel=False, verbose=False, raise_error=True, n_jobs=-1,
                      joblib_backend='loky', **params):
    """
    Generic function to run a sorter via function approach.

    Two usages with name or class:

    by name:
       >>> sorting = run_sorter('tridesclous', recording)

    by class:
       >>> sorting = run_sorter(TridesclousSorter, recording)

    Parameters
    ----------
    sorter_name_or_class: str or SorterClass
        The sorter to retrieve default parameters from
    recording: RecordingExtractor
        The recording extractor to be spike sorted
    output_folder: str or Path
        Path to output folder
    delete_output_folder: bool
        If True, output folder is deleted (default False)
    grouping_property: str
        Splits spike sorting by 'grouping_property' (e.g. 'groups')
    parallel: bool
        If True and spike sorting is by 'grouping_property', spike sorting jobs are launched in parallel
    verbose: bool
        If True, output is verbose
    raise_error: bool
        If True, an error is raised if spike sorting fails (default). If False, the process continues and the error is
        logged in the log file.
    n_jobs: int
        Number of jobs when parallel=True (default=-1)
    joblib_backend: str
        joblib backend when parallel=True (default='loky')
    **params: keyword args
        Spike sorter specific arguments (they can be retrieved with 'get_default_params(sorter_name_or_class)'

    Returns
    -------
    sortingextractor: SortingExtractor
        The spike sorted data

    """
    if isinstance(sorter_name_or_class, str):
        SorterClass = sorter_dict[sorter_name_or_class]
    elif sorter_name_or_class in sorter_full_list:
        SorterClass = sorter_name_or_class
    else:
        raise ValueError('Unknown sorter')

    sorter = SorterClass(recording=recording, output_folder=output_folder, grouping_property=grouping_property,
                         verbose=verbose, delete_output_folder=delete_output_folder)
    sorter.set_params(**params)
    sorter.run(raise_error=raise_error, parallel=parallel, n_jobs=n_jobs, joblib_backend=joblib_backend)
    sortingextractor = sorter.get_result(raise_error=raise_error)

    return sortingextractor


def available_sorters():
    """
    Lists available sorters.
    """
    return sorted(list(sorter_dict.keys()))


def installed_sorters():
    """
    Lists installed sorters.
    """
    l = sorted([s.sorter_name for s in sorter_full_list if s.is_installed()])
    return l


def print_sorter_versions():
    """
    Prints versions of all installed sorters.
    """
    txt = ''
    for name in installed_sorters():
        version = sorter_dict[name].get_sorter_version()
        txt += '{}: {}\n'.format(name, version)
    txt = txt[:-1]
    print(txt)


def get_default_params(sorter_name_or_class):
    """
    Returns default parameters for the specified sorter.

    Parameters
    ----------
    sorter_name_or_class: str or SorterClass
        The sorter to retrieve default parameters from

    Returns
    -------
    default_params: dict
        Dictionary with default params for the specified sorter
    """
    if isinstance(sorter_name_or_class, str):
        SorterClass = sorter_dict[sorter_name_or_class]
    elif sorter_name_or_class in sorter_full_list:
        SorterClass = sorter_name_or_class
    else:
        raise (ValueError('Unknown sorter'))

    return SorterClass.default_params()


def get_params_description(sorter_name_or_class):
    """
    Returns a description of the parameters for the specified sorter.

    Parameters
    ----------
    sorter_name_or_class: str or SorterClass
        The sorter to retrieve parameters description from

    Returns
    -------
    params_description: dict
        Dictionary with parameter description
    """
    if isinstance(sorter_name_or_class, str):
        SorterClass = sorter_dict[sorter_name_or_class]
    elif sorter_name_or_class in sorter_full_list:
        SorterClass = sorter_name_or_class
    else:
        raise (ValueError('Unknown sorter'))

    return SorterClass.params_description()


def get_sorter_description(sorter_name_or_class):
    """
    Returns a brief description of the of the specified sorter.

    Parameters
    ----------
    sorter_name_or_class: str or SorterClass
        The sorter to retrieve description from

    Returns
    -------
    params_description: dict
        Dictionary with parameter description
    """

    if isinstance(sorter_name_or_class, str):
        SorterClass = sorter_dict[sorter_name_or_class]
    elif sorter_name_or_class in sorter_full_list:
        SorterClass = sorter_name_or_class
    else:
        raise (ValueError('Unknown sorter'))

    return SorterClass.sorter_description


def run_hdsort(*args, **kwargs):
    """
    Runs HDsort sorter

    Parameters
    ----------
    *args: arguments of 'run_sorter'
        recording: RecordingExtractor
            The recording extractor to be spike sorted
        output_folder: str or Path
            Path to output folder
        delete_output_folder: bool
            If True, output folder is deleted (default False)
        grouping_property: str
            Splits spike sorting by 'grouping_property' (e.g. 'groups')
        parallel: bool
            If True and spike sorting is by 'grouping_property', spike sorting jobs are launched in parallel
        verbose: bool
            If True, output is verbose
        raise_error: bool
            If True, an error is raised if spike sorting fails (default). If False, the process continues and the error
            is logged in the log file
        n_jobs: int
            Number of jobs when parallel=True (default=-1)
        joblib_backend: str
            joblib backend when parallel=True (default='loky')
    **kwargs: keyword args
        Spike sorter specific arguments (they can be retrieved with 'get_default_params('hdsort')

    Returns
    -------
    sortingextractor: SortingExtractor
        The spike sorted data
    """
    return run_sorter('hdsort', *args, **kwargs)


def run_klusta(*args, **kwargs):
    """
    Runs klusta sorter

    Parameters
    ----------
    *args: arguments of 'run_sorter'
        recording: RecordingExtractor
            The recording extractor to be spike sorted
        output_folder: str or Path
            Path to output folder
        delete_output_folder: bool
            If True, output folder is deleted (default False)
        grouping_property: str
            Splits spike sorting by 'grouping_property' (e.g. 'groups')
        parallel: bool
            If True and spike sorting is by 'grouping_property', spike sorting jobs are launched in parallel
        verbose: bool
            If True, output is verbose
        raise_error: bool
            If True, an error is raised if spike sorting fails (default). If False, the process continues and the error
            is logged in the log file
        n_jobs: int
            Number of jobs when parallel=True (default=-1)
        joblib_backend: str
            joblib backend when parallel=True (default='loky')
    **kwargs: keyword args
        Spike sorter specific arguments (they can be retrieved with 'get_default_params('klusta')

    Returns
    -------
    sortingextractor: SortingExtractor
        The spike sorted data
    """
    return run_sorter('klusta', *args, **kwargs)


def run_tridesclous(*args, **kwargs):
    """
    Runs tridesclous sorter

    Parameters
    ----------
    *args: arguments of 'run_sorter'
        recording: RecordingExtractor
            The recording extractor to be spike sorted
        output_folder: str or Path
            Path to output folder
        delete_output_folder: bool
            If True, output folder is deleted (default False)
        grouping_property: str
            Splits spike sorting by 'grouping_property' (e.g. 'groups')
        parallel: bool
            If True and spike sorting is by 'grouping_property', spike sorting jobs are launched in parallel
        verbose: bool
            If True, output is verbose
        raise_error: bool
            If True, an error is raised if spike sorting fails (default). If False, the process continues and the error
            is logged in the log file
        n_jobs: int
            Number of jobs when parallel=True (default=-1)
        joblib_backend: str
            joblib backend when parallel=True (default='loky')
    **kwargs: keyword args
        Spike sorter specific arguments (they can be retrieved with 'get_default_params('tridesclous')

    Returns
    -------
    sortingextractor: SortingExtractor
        The spike sorted data
    """
    return run_sorter('tridesclous', *args, **kwargs)


def run_mountainsort4(*args, **kwargs):
    """
    Runs mountainsort4 sorter

    Parameters
    ----------
    *args: arguments of 'run_sorter'
        recording: RecordingExtractor
            The recording extractor to be spike sorted
        output_folder: str or Path
            Path to output folder
        delete_output_folder: bool
            If True, output folder is deleted (default False)
        grouping_property: str
            Splits spike sorting by 'grouping_property' (e.g. 'groups')
        parallel: bool
            If True and spike sorting is by 'grouping_property', spike sorting jobs are launched in parallel
        verbose: bool
            If True, output is verbose
        raise_error: bool
            If True, an error is raised if spike sorting fails (default). If False, the process continues and the error
            is logged in the log file
        n_jobs: int
            Number of jobs when parallel=True (default=-1)
        joblib_backend: str
            joblib backend when parallel=True (default='loky')
    **kwargs: keyword args
        Spike sorter specific arguments (they can be retrieved with 'get_default_params('mountainsort4')

    Returns
    -------
    sortingextractor: SortingExtractor
        The spike sorted data
    """
    return run_sorter('mountainsort4', *args, **kwargs)


def run_ironclust(*args, **kwargs):
    """
    Runs ironclust sorter

    Parameters
    ----------
    *args: arguments of 'run_sorter'
        recording: RecordingExtractor
            The recording extractor to be spike sorted
        output_folder: str or Path
            Path to output folder
        delete_output_folder: bool
            If True, output folder is deleted (default False)
        grouping_property: str
            Splits spike sorting by 'grouping_property' (e.g. 'groups')
        parallel: bool
            If True and spike sorting is by 'grouping_property', spike sorting jobs are launched in parallel
        verbose: bool
            If True, output is verbose
        raise_error: bool
            If True, an error is raised if spike sorting fails (default). If False, the process continues and the error
            is logged in the log file
        n_jobs: int
            Number of jobs when parallel=True (default=-1)
        joblib_backend: str
            joblib backend when parallel=True (default='loky')
    **kwargs: keyword args
        Spike sorter specific arguments (they can be retrieved with 'get_default_params('ironclust')

    Returns
    -------
    sortingextractor: SortingExtractor
        The spike sorted data
    """
    return run_sorter('ironclust', *args, **kwargs)


def run_kilosort(*args, **kwargs):
    """
    Runs kilosort sorter

    Parameters
    ----------
    *args: arguments of 'run_sorter'
        recording: RecordingExtractor
            The recording extractor to be spike sorted
        output_folder: str or Path
            Path to output folder
        delete_output_folder: bool
            If True, output folder is deleted (default False)
        grouping_property: str
            Splits spike sorting by 'grouping_property' (e.g. 'groups')
        parallel: bool
            If True and spike sorting is by 'grouping_property', spike sorting jobs are launched in parallel
        verbose: bool
            If True, output is verbose
        raise_error: bool
            If True, an error is raised if spike sorting fails (default). If False, the process continues and the error
            is logged in the log file
        n_jobs: int
            Number of jobs when parallel=True (default=-1)
        joblib_backend: str
            joblib backend when parallel=True (default='loky')
    **kwargs: keyword args
        Spike sorter specific arguments (they can be retrieved with 'get_default_params('kilosort')

    Returns
    -------
    sortingextractor: SortingExtractor
        The spike sorted data
    """
    return run_sorter('kilosort', *args, **kwargs)


def run_kilosort2(*args, **kwargs):
    """
    Runs kilosort2 sorter

    Parameters
    ----------
    *args: arguments of 'run_sorter'
        recording: RecordingExtractor
            The recording extractor to be spike sorted
        output_folder: str or Path
            Path to output folder
        delete_output_folder: bool
            If True, output folder is deleted (default False)
        grouping_property: str
            Splits spike sorting by 'grouping_property' (e.g. 'groups')
        parallel: bool
            If True and spike sorting is by 'grouping_property', spike sorting jobs are launched in parallel
        verbose: bool
            If True, output is verbose
        raise_error: bool
            If True, an error is raised if spike sorting fails (default). If False, the process continues and the error
            is logged in the log file
        n_jobs: int
            Number of jobs when parallel=True (default=-1)
        joblib_backend: str
            joblib backend when parallel=True (default='loky')
    **kwargs: keyword args
        Spike sorter specific arguments (they can be retrieved with 'get_default_params('kilosort2')

    Returns
    -------
    sortingextractor: SortingExtractor
        The spike sorted data
    """
    return run_sorter('kilosort2', *args, **kwargs)

def run_kilosort2_5(*args, **kwargs):
    """
    Runs kilosort2_5 sorter

    Parameters
    ----------
    *args: arguments of 'run_sorter'
        recording: RecordingExtractor
            The recording extractor to be spike sorted
        output_folder: str or Path
            Path to output folder
        delete_output_folder: bool
            If True, output folder is deleted (default False)
        grouping_property: str
            Splits spike sorting by 'grouping_property' (e.g. 'groups')
        parallel: bool
            If True and spike sorting is by 'grouping_property', spike sorting jobs are launched in parallel
        verbose: bool
            If True, output is verbose
        raise_error: bool
            If True, an error is raised if spike sorting fails (default). If False, the process continues and the error
            is logged in the log file
        n_jobs: int
            Number of jobs when parallel=True (default=-1)
        joblib_backend: str
            joblib backend when parallel=True (default='loky')
    **kwargs: keyword args
        Spike sorter specific arguments (they can be retrieved with 'get_default_params('kilosort2')

    Returns
    -------
    sortingextractor: SortingExtractor
        The spike sorted data
    """
    return run_sorter('kilosort2_5', *args, **kwargs)


def run_kilosort3(*args, **kwargs):
    """
    Runs kilosort3 sorter

    Parameters
    ----------
    *args: arguments of 'run_sorter'
        recording: RecordingExtractor
            The recording extractor to be spike sorted
        output_folder: str or Path
            Path to output folder
        delete_output_folder: bool
            If True, output folder is deleted (default False)
        grouping_property: str
            Splits spike sorting by 'grouping_property' (e.g. 'groups')
        parallel: bool
            If True and spike sorting is by 'grouping_property', spike sorting jobs are launched in parallel
        verbose: bool
            If True, output is verbose
        raise_error: bool
            If True, an error is raised if spike sorting fails (default). If False, the process continues and the error
            is logged in the log file
        n_jobs: int
            Number of jobs when parallel=True (default=-1)
        joblib_backend: str
            joblib backend when parallel=True (default='loky')
    **kwargs: keyword args
        Spike sorter specific arguments (they can be retrieved with 'get_default_params('kilosort3')

    Returns
    -------
    sortingextractor: SortingExtractor
        The spike sorted data
    """
    return run_sorter('kilosort3', *args, **kwargs)


def run_spykingcircus(*args, **kwargs):
    """
    Runs spykingcircus sorter

    Parameters
    ----------
    *args: arguments of 'run_sorter'
        recording: RecordingExtractor
            The recording extractor to be spike sorted
        output_folder: str or Path
            Path to output folder
        delete_output_folder: bool
            If True, output folder is deleted (default False)
        grouping_property: str
            Splits spike sorting by 'grouping_property' (e.g. 'groups')
        parallel: bool
            If True and spike sorting is by 'grouping_property', spike sorting jobs are launched in parallel
        verbose: bool
            If True, output is verbose
        raise_error: bool
            If True, an error is raised if spike sorting fails (default). If False, the process continues and the error
            is logged in the log file
        n_jobs: int
            Number of jobs when parallel=True (default=-1)
        joblib_backend: str
            joblib backend when parallel=True (default='loky')
    **kwargs: keyword args
        Spike sorter specific arguments (they can be retrieved with 'get_default_params('spykingcircus')

    Returns
    -------
    sortingextractor: SortingExtractor
        The spike sorted data
    """
    return run_sorter('spykingcircus', *args, **kwargs)


def run_herdingspikes(*args, **kwargs):
    """
    Runs herdingspikes sorter

    Parameters
    ----------
    *args: arguments of 'run_sorter'
        recording: RecordingExtractor
            The recording extractor to be spike sorted
        output_folder: str or Path
            Path to output folder
        delete_output_folder: bool
            If True, output folder is deleted (default False)
        grouping_property: str
            Splits spike sorting by 'grouping_property' (e.g. 'groups')
        parallel: bool
            If True and spike sorting is by 'grouping_property', spike sorting jobs are launched in parallel
        verbose: bool
            If True, output is verbose
        raise_error: bool
            If True, an error is raised if spike sorting fails (default). If False, the process continues and the error
            is logged in the log file
        n_jobs: int
            Number of jobs when parallel=True (default=-1)
        joblib_backend: str
            joblib backend when parallel=True (default='loky')
    **kwargs: keyword args
        Spike sorter specific arguments (they can be retrieved with 'get_default_params('herdingspikes')

    Returns
    -------
    sortingextractor: SortingExtractor
        The spike sorted data
    """
    return run_sorter('herdingspikes', *args, **kwargs)


def run_waveclus(*args, **kwargs):
    """
    Runs waveclus sorter

    Parameters
    ----------
    *args: arguments of 'run_sorter'
        recording: RecordingExtractor
            The recording extractor to be spike sorted
        output_folder: str or Path
            Path to output folder
        delete_output_folder: bool
            If True, output folder is deleted (default False)
        grouping_property: str
            Splits spike sorting by 'grouping_property' (e.g. 'groups')
        parallel: bool
            If True and spike sorting is by 'grouping_property', spike sorting jobs are launched in parallel
        verbose: bool
            If True, output is verbose
        raise_error: bool
            If True, an error is raised if spike sorting fails (default). If False, the process continues and the error
            is logged in the log file
        n_jobs: int
            Number of jobs when parallel=True (default=-1)
        joblib_backend: str
            joblib backend when parallel=True (default='loky')
    **kwargs: keyword args
        Spike sorter specific arguments (they can be retrieved with 'get_default_params('waveclus')

    Returns
    -------
    sortingextractor: SortingExtractor
        The spike sorted data
    """
    return run_sorter('waveclus', *args, **kwargs)


def run_combinato(*args, **kwargs):
    """
    Runs combinato sorter

    Parameters
    ----------
    *args: arguments of 'run_sorter'
        recording: RecordingExtractor
            The recording extractor to be spike sorted
        output_folder: str or Path
            Path to output folder
        delete_output_folder: bool
            If True, output folder is deleted (default False)
        grouping_property: str
            Splits spike sorting by 'grouping_property' (e.g. 'groups')
        parallel: bool
            If True and spike sorting is by 'grouping_property', spike sorting jobs are launched in parallel
        verbose: bool
            If True, output is verbose
        raise_error: bool
            If True, an error is raised if spike sorting fails (default). If False, the process continues and the error
            is logged in the log file
        n_jobs: int
            Number of jobs when parallel=True (default=-1)
        joblib_backend: str
            joblib backend when parallel=True (default='loky')
    **kwargs: keyword args
        Spike sorter specific arguments (they can be retrieved with 'get_default_params('combinato')

    Returns
    -------
    sortingextractor: SortingExtractor
        The spike sorted data
    """
    return run_sorter('combinato', *args, **kwargs)


def run_yass(*args, **kwargs):
    """
    Runs YASS sorter

    Parameters
    ----------
    *args: arguments of 'run_sorter'
        recording: RecordingExtractor
            The recording extractor to be spike sorted
        output_folder: str or Path
            Path to output folder
        delete_output_folder: bool
            If True, output folder is deleted (default False)
        grouping_property: str
            Splits spike sorting by 'grouping_property' (e.g. 'groups')
        parallel: bool
            If True and spike sorting is by 'grouping_property', spike sorting jobs are launched in parallel
        verbose: bool
            If True, output is verbose
        raise_error: bool
            If True, an error is raised if spike sorting fails (default). If False, the process continues and the error
            is logged in the log file
        n_jobs: int
            Number of jobs when parallel=True (default=-1)
        joblib_backend: str
            joblib backend when parallel=True (default='loky')
    **kwargs: keyword args
        Spike sorter specific arguments (they can be retrieved with 'get_default_params('yass')

    Returns
    -------
    sortingextractor: SortingExtractor
        The spike sorted data
    """
    return run_sorter('yass', *args, **kwargs)
