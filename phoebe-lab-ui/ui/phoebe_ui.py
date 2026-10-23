from nicegui import ui, Client
import numpy as np
import plotly.graph_objects as go
from pathlib import Path
from client.session_api import SessionAPI
from client.phoebe_api import PhoebeAPI
from ui.utils import time_to_phase, alias_data, flux_to_magnitude
from asyncio import get_event_loop


class PhoebeParameterWidget:
    """
    Parent class for all parameter widgets.
    """

    def __init__(self, twig: str, label: str, format: str = '%.3f', api=None, ui_hook=None, classes='flex-1 min-w-0', visible=True, sensitive=True, **kwargs):
        self.api = api  # Reference to API for setting values
        self.ui_hook = ui_hook  # Optional hook for UI updates

        # grab parameter information from the api:
        request = api.get_parameter(twig)
        if request['success']:
            par = request['result']
            value = par['value']
            self.uniqueid = par['uniqueid']
            self.twig = par['twig']  # fully qualified twig
        else:
            raise ValueError(f"Failed to retrieve parameter {twig}: {request.get('error', 'Unknown error')}")

        if par['Class'] in ['FloatParameter', 'IntParameter']:
            order_of_mag = np.floor(np.log10(np.abs(value))) if value != 0 else 0
            limits = par['limits']
            self.widget = ui.number(
                label=label,
                value=value,
                format=format,
                min=limits[0],
                max=limits[1],
                step=float(10**(order_of_mag-2))
            ).classes('flex-1 min-w-0')

        elif par['Class'] == 'ChoiceParameter':
            self.widget = ui.select(
                label=label,
                options=par['choices'],
                value=value
            ).classes(classes)

        elif par['Class'] == 'BoolParameter':
            self.widget = ui.checkbox(
                text=label,
                value=value
            ).classes('flex-1 min-w-0')

        else:
            raise NotImplementedError(f"Parameter class {par['Class']} not supported yet.")

        # set default visibility and sensitivity:
        self.visible = visible
        self.sensitive = sensitive

        # if parameter is constrained, disable the widget
        response = api.is_parameter_constrained(uniqueid=self.uniqueid)
        if response['success']:
            self.set_sensitive(not response['result'])

        self.widget.on('update:model-value', self.on_value_changed)

    def set_sensitive(self, sensitive: bool):
        if sensitive:
            self.widget.enable()
            self.sensitive = True
        else:
            self.widget.disable()
            self.sensitive = False

    def set_visible(self, visible: bool):
        self.widget.classes(remove='hidden') if visible else self.widget.classes(add='hidden')
        self.visible = visible

    def update_uniqueid(self):
        response = self.api.get_uniqueid(twig=self.twig)
        if response['success']:
            self.uniqueid = response['result']
        else:
            self.uniqueid = None

    def get_value(self):
        if self.widget:
            return self.widget.value

    def set_value(self, value):
        if self.widget:
            self.widget.value = value

    def on_value_changed(self, event):
        if event is None:
            return

        value = self.widget.value

        try:
            response = self.api.set_value(uniqueid=self.uniqueid, value=value)
            if not response.get('success', False):
                ui.notify(f'Failed to set {self.twig}: {response.get("error", "Unknown error")}', type='negative')
        except Exception as e:
            ui.notify(f'Error setting {self.twig}: {str(e)}', type='negative')

        if self.ui_hook:
            self.ui_hook(value)


class PhoebeAdjustableParameterWidget:
    """
    Widget for a single Phoebe parameter with value, adjustment checkbox, and step size.
    """

    def __init__(self, twig: str, label: str, step: float = 0.001, vformat: str = '%.3f',
                 sformat: str = '%.3f', adjust: bool = False, api=None, ui_ref=None, ui_hook=None, **kwargs):
        self.step = step
        self.adjust = adjust
        self.ui = ui_ref

        with ui.row().classes('items-center gap-2 w-full') as self.container:
            # Parameter label
            ui.label(f'{label}:').classes('w-24 flex-shrink-0 text-sm')

            # Value input
            self.value_input = PhoebeParameterWidget(
                twig=twig,
                label='Value',
                format=vformat,
                api=api,
                ui_hook=ui_hook,
                **kwargs
            )

            # Checkbox for adjustment
            self.adjust_checkbox = ui.checkbox(text='Adjust', value=adjust).classes('flex-shrink-0')
            self.adjust_checkbox.on('update:model-value', self.on_adjust_toggled)

            # Step size input (after checkbox)
            self.step_input = ui.number(
                label='Step',
                value=step,
                format=sformat,
                step=step/10
            ).classes('flex-1 min-w-0')

            # Set initial state of step input
            self.on_adjust_toggled()

        # Set twig and uniqueid to that of the value input:
        self.twig = self.value_input.twig
        self.uniqueid = self.value_input.uniqueid

        # Set initial visibility and sensitivity:
        self.visible = True
        self.sensitive = True

    def set_visible(self, visible: bool):
        self.container.classes(remove='hidden') if visible else self.container.classes(add='hidden')
        self.visible = visible

    def set_sensitive(self, sensitive: bool):
        self.value_input.set_sensitive(sensitive)
        self.sensitive = self.value_input.sensitive

    def update_uniqueid(self):
        self.value_input.update_uniqueid()
        self.uniqueid = self.value_input.uniqueid

    def get_twig(self):
        return self.value_input.twig

    def get_value(self):
        return self.value_input.widget.value

    def set_value(self, value):
        self.value_input.set_value(value)

    def on_value_changed(self, event=None):
        return self.value_input.on_value_changed(event)

    def on_adjust_toggled(self):
        """Handle adjust checkbox state change."""
        self.adjust = self.adjust_checkbox.value

        if self.adjust:
            self.step_input.enable()
            self.step_input.classes(remove='text-gray-400')
            if self.ui.fully_initialized:
                self.ui.add_parameter_to_solver_table(self)
        else:
            self.step_input.disable()
            self.step_input.classes(add='text-gray-400')
            if self.ui.fully_initialized:
                self.ui.remove_parameter_from_solver_table(self)


class Dataset:
    """
    Fully encapsulated dataset component managing data model, UI, and interactions.
    Handles dataset creation, editing, display, and synchronization with bundle.
    """

    def __init__(self, api):
        self.api = api

        # Internal data model
        self.datasets = {}
        self._dataset_template = {
            'kind': 'lc',
            'dataset': 'ds01',
            'passband': 'Johnson:V',
            'times': [],
            'fluxes': [],
            'model_fluxes': [],
            'rv1s': [],
            'rv2s': [],
            'model_rv1s': [],
            'model_rv2s': [],
            'sigmas': [],
            'filename': '',
            'n_points': 201,
            'phase_min': -0.5,
            'phase_max': 0.5,
            'data_points': 0,
            'plot_data': False,
            'plot_model': False
        }

        # UI references (will be set during mount)
        self.dataset_table = None
        self.dataset_dialog = None
        self.widgets = {}
        self.selected_row = None

        # File upload state
        self.data_file = None
        self.data_content = None

        # Dialog state
        self._editing_mode = False
        self._editing_dataset = None

    def add(self, **kwargs):
        """Add a dataset to both internal model and bundle via API."""
        kind = kwargs.pop('kind', None)
        dataset = kwargs.pop('dataset', None)

        if not kind:
            raise ValueError('Dataset kind not specified.')
        if not dataset:
            raise ValueError('Dataset label not specified.')
        if dataset in self.datasets:
            raise ValueError(f'Dataset {dataset} already exists -- please choose a unique label.')

        dataset_meta = self._dataset_template.copy()
        dataset_meta.update({'kind': kind, 'dataset': dataset, **kwargs})
        self.datasets[dataset] = dataset_meta

        compute_phases = np.linspace(
            dataset_meta['phase_min'],
            dataset_meta['phase_max'],
            dataset_meta['n_points']
        )

        # Call API to add the dataset to bundle
        params = {
            'dataset': dataset_meta.get('dataset'),
            'passband': dataset_meta.get('passband', 'Johnson:V'),
            'compute_phases': compute_phases,
            'times': dataset_meta.get('times', []),
            'sigmas': dataset_meta.get('sigmas', [])
        }
        if kind == 'lc':
            params['fluxes'] = dataset_meta.get('fluxes', [])
        if kind == 'rv':
            params['rv1s'] = dataset_meta.get('rv1s', [])
            params['rv2s'] = dataset_meta.get('rv2s', [])

        self.api.add_dataset(kind, **params)

        # Set pblum_mode to dataset-scaled if we have actual data
        if len(dataset_meta['fluxes']) > 0 or len(dataset_meta['rv1s']) > 0 or len(dataset_meta['rv2s']) > 0:
            self.api.set_value(twig=f'pblum_mode@{dataset}', value='dataset-scaled')

    def remove(self, dataset):
        """Remove a dataset from both internal model and bundle."""
        if dataset not in self.datasets:
            raise ValueError(f'Dataset {dataset} does not exist.')

        self.api.remove_dataset(dataset)
        del self.datasets[dataset]

    def readd_all(self):
        """Re-add all datasets to bundle (used after morphology change)."""
        for dataset in self.datasets.values():
            compute_phases = np.linspace(
                dataset['phase_min'],
                dataset['phase_max'],
                dataset['n_points']
            )

            params = {
                'dataset': dataset.get('dataset'),
                'passband': dataset.get('passband'),
                'compute_phases': compute_phases,
                'times': dataset.get('times'),
                'sigmas': dataset.get('sigmas')
            }

            if dataset['kind'] == 'lc':
                params['fluxes'] = dataset.get('fluxes', [])
            if dataset['kind'] == 'rv':
                params['rv1s'] = dataset.get('rv1s', [])
                params['rv2s'] = dataset.get('rv2s', [])

            self.api.add_dataset(dataset['kind'], **params)
            if len(dataset['fluxes']) > 0 or len(dataset['rv1s']) > 0 or len(dataset['rv2s']) > 0:
                self.api.set_value(twig=f'pblum_mode@{dataset["dataset"]}', value='dataset-scaled')

    def sync_from_bundle(self):
        """Synchronize internal model from bundle via API (bundle → model)."""
        response = self.api.get_datasets()

        if not response.get('success', False):
            ui.notify(f"Failed to get datasets from bundle: {response.get('error', 'Unknown error')}", type='negative')
            return

        bundle_datasets = response['result']['datasets']
        self.datasets = {}

        # Populate model from bundle data
        for ds_label, ds_data in bundle_datasets.items():
            print(f'{type(ds_data["times"])=}')
            dataset_meta = self._dataset_template.copy()
            dataset_meta.update({
                'kind': ds_data.get('kind', 'lc'),
                'dataset': ds_label,
                'passband': ds_data.get('passband', 'Johnson:V'),
                'times': np.array(ds_data.get('times', [])) if ds_data.get('times') is not None else np.array([]),
                'fluxes': np.array(ds_data.get('fluxes', [])) if ds_data.get('fluxes') is not None else np.array([]),
                'rv1s': np.array(ds_data.get('rv1s', [])) if ds_data.get('rv1s') is not None else np.array([]),
                'rv2s': np.array(ds_data.get('rv2s', [])) if ds_data.get('rv2s') is not None else np.array([]),
                'sigmas': np.array(ds_data.get('sigmas', [])) if ds_data.get('sigmas') is not None else np.array([]),
                'data_points': len(ds_data.get('times', [])) if ds_data.get('times') is not None else 0,
                'filename': 'From Bundle' if ds_data.get('times') else 'Synthetic',
                'n_points': 201,
                'phase_min': -0.5,
                'phase_max': 0.5,
                'model_fluxes': [],
                'model_rv1s': [],
                'model_rv2s': [],
                'plot_data': False,
                'plot_model': False
            })
            self.datasets[ds_label] = dataset_meta

    def _collect_from_dialog(self):
        """Collect dataset parameters from dialog widgets."""
        params = {
            'kind': self.widgets['dataset_kind'].value,
            'dataset': self.widgets['dataset_label'].value,
            'passband': self.widgets['dataset_passband'].value,
            'n_points': int(self.widgets['dataset_n_points'].value),
            'phase_min': self.widgets['dataset_phase_min'].value,
            'phase_max': self.widgets['dataset_phase_max'].value,
        }

        # Add data if available (from file upload)
        if self.data_file:
            params['filename'] = self.data_file

            if self.data_content:
                data_content = np.genfromtxt(self.data_content)
            else:
                data_content = np.genfromtxt(self.data_file)

            params['data_points'] = len(data_content)
            params['times'] = data_content[:, 0]

            kind = params.get('kind', 'lc')
            if kind == 'lc':
                params['fluxes'] = data_content[:, 1]
            elif kind == 'rv':
                params['rv1s'] = data_content[:, 1]
                params['rv2s'] = data_content[:, 1]  # TODO: handle separate RV components

            params['sigmas'] = data_content[:, 2]
        else:
            params['filename'] = 'Synthetic'
            params['data_points'] = 0

        return params

    def _populate_dialog_from_dataset(self, dataset_label):
        """Populate dialog widgets from an existing dataset."""
        if dataset_label not in self.datasets:
            ui.notify(f"Dataset {dataset_label} not found", type='warning')
            return

        dataset_meta = self.datasets[dataset_label]

        # Mark as editing mode
        self._editing_mode = True
        self._editing_dataset = dataset_label

        # Update dialog UI for edit mode
        self.dialog_title.text = f'Edit Dataset: {dataset_label}'
        self.dialog_action_button.text = 'Save'

        # Populate all fields
        self.widgets['dataset_kind'].value = dataset_meta.get('kind')
        self.widgets['dataset_label'].value = dataset_meta.get('dataset')
        self.widgets['dataset_passband'].value = dataset_meta.get('passband')
        self.widgets['dataset_n_points'].value = dataset_meta.get('n_points')
        self.widgets['dataset_phase_min'].value = dataset_meta.get('phase_min')
        self.widgets['dataset_phase_max'].value = dataset_meta.get('phase_max')

        # Disable label widget (can't change dataset designation)
        self.widgets['dataset_label'].disable()

    def _refresh_table(self):
        """Refresh the dataset table UI from internal model."""
        if not self.dataset_table:
            return

        row_data = []
        for ds_label, ds_meta in self.datasets.items():
            phase_min = ds_meta.get('phase_min', -0.5)
            phase_max = ds_meta.get('phase_max', 0.5)
            n_points = ds_meta.get('n_points', 201)
            phases_str = f'({phase_min:.2f}, {phase_max:.2f}, {n_points})'

            row_data.append({
                'label': ds_label,
                'type': ds_meta['kind'],
                'passband': ds_meta['passband'],
                'filename': ds_meta['filename'],
                'phases': phases_str,
                'data_points': ds_meta['data_points'],
                'plot_data': ds_meta.get('plot_data', False),
                'plot_model': ds_meta.get('plot_model', False)
            })

        self.dataset_table.options['rowData'] = row_data
        self.dataset_table.update()

    def mount_panel(self):
        """Mount the dataset management panel UI (table + buttons)."""
        with ui.expansion('Dataset Management', icon='table_chart', value=True).classes('w-full mb-2').style('padding: 2px;'):
            # Enhanced dataset control grid
            self.dataset_table = ui.aggrid({
                'columnDefs': [
                    {'field': 'label', 'headerName': 'Dataset', 'width': 120, 'sortable': True},
                    {'field': 'type', 'headerName': 'Type', 'width': 60, 'sortable': True},
                    {'field': 'phases', 'headerName': 'Phases', 'width': 100, 'sortable': True},
                    {'field': 'data_points', 'headerName': 'Data Points', 'width': 90, 'sortable': True, 'type': 'numericColumn'},
                    {'field': 'passband', 'headerName': 'Passband', 'width': 100, 'sortable': True},
                    {'field': 'filename', 'headerName': 'Source', 'width': 120, 'sortable': True},
                    {
                        'field': 'plot_data',
                        'headerName': 'Plot Data',
                        'width': 90,
                        'cellRenderer': 'agCheckboxCellRenderer',
                        ':editable': 'params => { return params.data.filename !== "Synthetic"; }'
                    },
                    {
                        'field': 'plot_model',
                        'headerName': 'Plot Model',
                        'width': 90,
                        'cellRenderer': 'agCheckboxCellRenderer',
                        'editable': True
                    }
                ],
                'rowData': [],
                'domLayout': 'autoHeight',
                'suppressHorizontalScroll': False,
                'enableCellChangeFlash': True,
                'rowSelection': 'single',
                'overlayNoRowsTemplate': 'No datasets added. Click "Add" to define a synthetic dataset or load observations.',
            }).classes('w-full').style('height: auto; min-height: 80px; max-height: 300px;')

            # Listen to events
            self.dataset_table.on('rowSelected', self._on_row_selected)
            self.dataset_table.on('cellDoubleClicked', self._on_cell_double_clicked)
            self.dataset_table.on('cellValueChanged', self._on_checkbox_toggled)

            # Dataset action buttons
            with ui.row().classes('gap-2 justify-end w-full'):
                ui.button('Add', on_click=self._on_add_clicked, icon='add').props('flat color=primary')
                ui.button('Edit', on_click=self._on_edit_clicked, icon='edit').props('flat color=secondary')
                ui.button('Remove', on_click=self._on_remove_clicked, icon='delete').props('flat color=negative')

    def mount_dialog(self):
        """Mount the dataset creation/edit dialog."""
        with ui.dialog() as self.dataset_dialog, ui.card().classes('w-[800px] h-[600px]'):
            self.dialog_title = ui.label('Add Dataset').classes('text-xl font-bold mb-4')

            with ui.column().classes('w-full gap-4'):
                self.widgets['dataset_kind'] = ui.select(
                    options={'lc': 'Light Curve', 'rv': 'RV Curve'},
                    label='Dataset type'
                ).classes('w-full')

                self.widgets['dataset_label'] = ui.input(
                    label='Dataset Label',
                    placeholder='e.g., lc01, rv01, etc.',
                ).classes('w-full')

                self.widgets['dataset_passband'] = ui.select(
                    options=['GoChile:R', 'GoChile:G', 'GoChile:B', 'GoChile:L', 'TESS:T', 'Kepler:mean', 'Johnson:V'],
                    label='Passband'
                ).classes('w-full')

                # Phase parameters section
                with ui.expansion('Model', icon='straighten', value=False).classes('w-full mt-4'):
                    with ui.row().classes('gap-2 w-full'):
                        self.widgets['dataset_phase_min'] = ui.number(
                            label='Phase min', value=-0.5, step=0.1, format='%.2f'
                        ).classes('flex-1')

                        self.widgets['dataset_phase_max'] = ui.number(
                            label='Phase max', value=0.5, step=0.1, format='%.2f'
                        ).classes('flex-1')

                        self.widgets['dataset_n_points'] = ui.number(
                            label='Length', value=201, min=20, max=10000, step=1, format='%d'
                        ).classes('flex-1')

            ui.separator().classes('my-4')

            with ui.expansion('Observations', icon='insert_chart', value=False).classes('w-full'):
                with ui.tabs().classes('w-full') as tabs:
                    example_tab = ui.tab('Example Files')
                    upload_tab = ui.tab('Upload File')

                with ui.tab_panels(tabs, value=example_tab).classes('w-full'):
                    # Example tab
                    with ui.tab_panel(example_tab):
                        ui.label('Select an example data file:').classes('mb-2')

                        examples_dir = Path(__file__).parent.parent / 'examples'
                        example_files = []

                        if examples_dir.exists():
                            for file_path in examples_dir.glob('*'):
                                example_files.append({
                                    'name': file_path.name,
                                    'path': str(file_path),
                                    'description': '',
                                })

                        if example_files:
                            example_cards = []

                            def toggle_card_selection(file_path, card_element):
                                if self.data_file == file_path:
                                    self.data_file = None
                                    card_element.classes(remove='bg-blue-100 border-blue-500 border-2')
                                    card_element.classes(add='bg-white border-gray-200')
                                else:
                                    for other_card in example_cards:
                                        other_card.classes(remove='bg-blue-100 border-blue-500 border-2')
                                        other_card.classes(add='bg-white border-gray-200')
                                    self.data_file = file_path
                                    card_element.classes(remove='bg-white border-gray-200')
                                    card_element.classes(add='bg-blue-100 border-blue-500 border-2')

                            with ui.column().classes('w-full gap-2'):
                                for file_info in example_files:
                                    with ui.card().classes('cursor-pointer hover:bg-gray-50 p-3 bg-white border-gray-200 border') as card:
                                        example_cards.append(card)
                                        ui.label(file_info['name']).classes('font-bold')
                                        ui.label(file_info['description']).classes('text-sm text-gray-600')
                                        card.on('click', lambda fp=file_info['path'], c=card: toggle_card_selection(fp, c))
                        else:
                            ui.label('No example files found').classes('text-gray-500')

                    # Upload tab
                    with ui.tab_panel(upload_tab):
                        ui.label('Upload a data file from your computer:').classes('mb-2')
                        ui.label('Supported formats: Space or tab-separated text files with columns:').classes('text-sm text-gray-600')
                        ui.label('Time, Flux/Magnitude/Velocity, Error').classes('text-sm text-gray-600 mb-4')

                        ui.upload(
                            max_file_size=10_000_000,
                            max_files=1,
                            on_upload=self._on_file_uploaded,
                        ).classes('w-full border-2 border-dashed border-gray-300 rounded-lg p-8 text-center')

            ui.separator().classes('my-4')

            with ui.row().classes('gap-2 justify-end w-full'):
                ui.button('Cancel', on_click=self.dataset_dialog.close).classes('bg-gray-500')
                self.dialog_action_button = ui.button('Add', icon='save', on_click=self._on_dialog_add_clicked).classes('bg-blue-500')

    def refresh(self):
        """Public method to refresh the table from model."""
        self._refresh_table()

    def _on_add_clicked(self):
        """Handle Add button click."""
        # Reset to add mode
        self._editing_mode = False
        self._editing_dataset = None

        # Update dialog UI for add mode
        self.dialog_title.text = 'Add Dataset'
        self.dialog_action_button.text = 'Add'

        # Clear and enable all fields
        self.widgets['dataset_kind'].value = 'lc'
        self.widgets['dataset_label'].value = f'ds{len(self.datasets)+1:02d}'
        self.widgets['dataset_label'].enable()
        self.widgets['dataset_passband'].value = ''
        self.widgets['dataset_n_points'].value = 201
        self.widgets['dataset_phase_min'].value = -0.5
        self.widgets['dataset_phase_max'].value = 0.5

        # Clear file upload state
        self.data_file = None
        self.data_content = None

        self.dataset_dialog.open()

    def _on_edit_clicked(self):
        """Handle Edit button click."""
        if not self.selected_row:
            ui.notify('Please select a dataset to edit.', type='warning')
            return
        dataset_label = self.selected_row['label']
        self._populate_dialog_from_dataset(dataset_label)
        self.dataset_dialog.open()

    def _on_cell_double_clicked(self, event):
        """Handle double-click on table cell to edit.

        Skip if user double-clicked on checkbox cells (plot_data, plot_model),
        otherwise open the edit dialog.
        """
        if not event.args:
            return

        # Get the column that was double-clicked
        column = event.args.get('colId', '')

        # Skip if double-clicking on checkbox columns
        if column in ['plot_data', 'plot_model']:
            return

        # Get the dataset label and open edit dialog
        if 'data' in event.args and 'label' in event.args['data']:
            dataset_label = event.args['data']['label']
            self._populate_dialog_from_dataset(dataset_label)
            self.dataset_dialog.open()

    def _on_remove_clicked(self):
        """Handle Remove button click."""
        if not self.selected_row:
            ui.notify('Please select a dataset to remove.', type='warning')
            return

        dataset = self.selected_row['label']

        with ui.dialog() as dialog, ui.card():
            ui.label(f'Are you sure you want to remove dataset "{dataset}"?').classes('text-lg font-bold')
            with ui.row().classes('gap-2 justify-end mt-4'):
                ui.button('Cancel', on_click=dialog.close).props('flat')
                ui.button('Remove', on_click=lambda: self._on_remove_confirmed(dataset, dialog), color='negative').props('flat')
        dialog.open()

    def _on_remove_confirmed(self, dataset, dialog):
        """Handle Remove confirmation."""
        self.remove(dataset)
        self._refresh_table()
        dialog.close()

    def _on_dialog_add_clicked(self):
        """Handle Add/Save button in dialog."""
        model = self._collect_from_dialog()

        try:
            if self._editing_mode:
                # Update existing dataset
                # Remove old version and add updated version
                if self._editing_dataset and self._editing_dataset in self.datasets:
                    self.remove(self._editing_dataset)
                self.add(**model)
                ui.notify(f'Dataset {model["dataset"]} updated successfully', type='positive')
            else:
                # Add new dataset
                self.add(**model)
                ui.notify(f'Dataset {model["dataset"]} added successfully', type='positive')
        except Exception as e:
            ui.notify(f'Error saving dataset: {e}', type='error')
            return

        self._refresh_table()
        self.dataset_dialog.close()

    def _on_row_selected(self, event):
        """Handle row selection in table."""
        if event.args and 'data' in event.args and 'label' in event.args['data']:
            self.selected_row = event.args['data']
        else:
            self.selected_row = None

    def _on_checkbox_toggled(self, event):
        """Handle checkbox toggle in table."""
        dataset = event.args['data']['label']
        field = event.args['colId']
        state = event.args['value']
        self.datasets[dataset][field] = state

    def _on_file_uploaded(self, event):
        """Handle file upload."""
        if event and event.name and event.content:
            self.data_file = event.name
            self.data_content = event.content
            ui.notify(f'File uploaded: {self.data_file}', type='success')
        else:
            ui.notify('File upload failed.', type='error')


class PhoebeUI:
    """Main Phoebe UI."""

    def __init__(self, session_api: SessionAPI = None, phoebe_api: PhoebeAPI = None):
        # there are many callbacks that depend on the UI being fully
        # initialized, so we keep the UI state explicitly:
        self.fully_initialized = False

        self.session_api = session_api
        self.phoebe_api = phoebe_api
        self.client_id = None  # Will be set when session is established
        self.user_first_name = None
        self.user_last_name = None

        # Parameters:
        self.parameters = {}

        # Reference to widgets:
        self.widgets = {}

        # Initialize dataset component:
        self.dataset = Dataset(api=self.phoebe_api)
        self.dataset.mount_dialog()  # Create dialog upfront

        # Show startup dialog first
        self.show_startup_dialog()

        if not self.client_id:
            ui.label('Error: No se pudo conectar con el servidor backend de PHOEBE. Asegúrate de que el API esté activo.').classes('text-negative text-lg p-4 font-bold')
            return

        # Create main UI (will be shown after dialog)
        with ui.splitter(value=30).classes('w-full h-screen') as self.main_splitter:
            # Left panel - Parameters, data, and controls
            with self.main_splitter.before:
                with ui.scroll_area().classes('w-full h-full p-4'):
                    self.create_parameter_panel()

            # Right panel - Data, plots and results
            with self.main_splitter.after:
                self.create_analysis_panel()

            # Allow plot width change on splitter drag
            # Handle plot resize on splitter change
            plot_id = self.lc_canvas.id
            plot_resize_js = f'Plotly.Plots.resize(getHtmlElement({plot_id}))'
            self.main_splitter.on_value_change(lambda: ui.run_javascript(plot_resize_js))

        self.fully_initialized = True

    def add_parameter(self, twig: str, label: str, step: float, adjust: bool, vformat: str = '%.3f', sformat: str = '%.3f', on_value_changed=None):
        parameter = PhoebeAdjustableParameterWidget(
            twig=twig,
            label=label,
            step=step,
            adjust=adjust,
            vformat=vformat,
            sformat=sformat,
            api=self.phoebe_api,
            ui_ref=self,
            ui_hook=on_value_changed,
        )

        # name the parameter by its fully qualified twig:
        self.parameters[parameter.twig] = parameter

    def create_parameter_panel(self):
        # Load/Save buttons
        with ui.row().classes('w-full gap-2 mb-4'):
            self.load_button = ui.button(
                'Load Model',
                icon='file_upload',
                on_click=self.on_load_model
            ).classes('flex-1 bg-blue-600 text-white')
            
            self.save_button = ui.button(
                'Save Model',
                icon='file_download',
                on_click=self.on_save_model
            ).classes('flex-1 bg-green-600 text-white')

        # Model selection
        self.parameters['backend@ui'] = PhoebeParameterWidget(
            twig='backend@ui',
            label='Computation Backend',
            api=self.phoebe_api,
            classes='w-full mb-4'
        )

        # Morphology selection
        self.parameters['morphology@ui'] = PhoebeParameterWidget(
            twig='morphology@ui',
            label='Binary star morphology type',
            api=self.phoebe_api,
            ui_hook=self.sync_ui_state,
            classes='w-full mb-4'
        )

        # Ephemerides parameters
        with ui.expansion('Ephemerides', icon='schedule', value=False).classes('w-full mb-4'):
            # Create parameter widgets for t0 and period
            self.add_parameter(
                twig='t0_supconj@binary',
                label='T₀ (BJD)',
                step=0.01,
                adjust=False,
                vformat='%.8f',
                sformat='%.3f',
                on_value_changed=self.on_ephemeris_changed
            )

            self.add_parameter(
                twig='period@binary',
                label='Period (d)',
                step=0.0001,
                adjust=False,
                vformat='%.8f',
                sformat='%.3f',
                on_value_changed=self.on_ephemeris_changed
            )

        # Primary star parameters
        with ui.expansion('Primary Star', icon='wb_sunny', value=False).classes('w-full mb-4'):
            self.add_parameter(
                twig='mass@primary@component',
                label='Mass (M₀)',
                step=0.01,
                adjust=False,
            )

            self.add_parameter(
                twig='requiv@primary@component',
                label='Radius (R₀)',
                step=0.01,
                adjust=False,
            )

            self.add_parameter(
                twig='teff@primary@component',
                label='Temperature (K)',
                vformat='%d',
                step=10.0,
                adjust=False,
            )

        # Secondary star parameters
        with ui.expansion('Secondary Star', icon='wb_sunny', value=False).classes('w-full mb-4'):
            self.add_parameter(
                twig='mass@secondary@component',
                label='Mass (M₀)',
                step=0.01,
                adjust=False,
            )

            self.add_parameter(
                twig='requiv@secondary@component',
                label='Radius (R₀)',
                step=0.01,
                adjust=False,
            )

            self.add_parameter(
                twig='teff@secondary@component',
                label='Temperature (K)',
                vformat='%d',
                step=10.0,
                adjust=False,
            )

        # Orbit parameters
        with ui.expansion('Orbit', icon='trip_origin', value=False).classes('w-full mb-4'):
            self.add_parameter(
                twig='incl@binary@component',
                label='Inclination (°)',
                step=0.1,
                adjust=False,
            )

            self.add_parameter(
                twig='ecc@binary@component',
                label='Eccentricity',
                step=0.01,
                adjust=False,
            )

            self.add_parameter(
                twig='per0@binary@component',
                label='Argument of periastron (°)',
                step=1.0,
                adjust=False,
            )

    def create_dataset_panel(self):
        with ui.expansion('Dataset Management', icon='table_chart', value=True).classes('w-full mb-2').style('padding: 2px;'):
            # Enhanced dataset control grid
            self.dataset_table = ui.aggrid({
                'columnDefs': [
                    {'field': 'label', 'headerName': 'Dataset', 'width': 120, 'sortable': True},
                    {'field': 'type', 'headerName': 'Type', 'width': 60, 'sortable': True},
                    {'field': 'phases', 'headerName': 'Phases', 'width': 100, 'sortable': True},
                    {'field': 'data_points', 'headerName': 'Data Points', 'width': 90, 'sortable': True, 'type': 'numericColumn'},
                    {'field': 'passband', 'headerName': 'Passband', 'width': 100, 'sortable': True},
                    {'field': 'filename', 'headerName': 'Source', 'width': 120, 'sortable': True},
                    {
                        'field': 'plot_data',
                        'headerName': 'Plot Data',
                        'width': 90,
                        'cellRenderer': 'agCheckboxCellRenderer',
                        ':editable': 'params => { return params.data.filename !== "Synthetic"; }'  # leading colon means js content instead of string
                    },
                    {
                        'field': 'plot_model',
                        'headerName': 'Plot Model',
                        'width': 90,
                        'cellRenderer': 'agCheckboxCellRenderer',
                        'editable': True
                    }
                ],
                'rowData': [],  # start with an empty table
                'domLayout': 'autoHeight',
                'suppressHorizontalScroll': False,
                'enableCellChangeFlash': True,
                'rowSelection': 'single',
                'overlayNoRowsTemplate': 'No datasets added. Click "Add" to define a synthetic dataset or load observations.',
                # 'theme': 'ag-theme-alpine'
            }).classes('w-full').style('height: auto; min-height: 80px; max-height: 300px;')

            # Store selected row for edit/remove operations
            self.selected_dataset_row = None

            # Listen to row selections:
            self.dataset_table.on('rowSelected', self.on_dataset_row_selected)

            # Listen to checkbox toggles
            self.dataset_table.on('cellValueChanged', self.on_dataset_panel_checkbox_toggled)

            # Dataset action buttons
            with ui.row().classes('gap-2 justify-end w-full'):
                ui.button(
                    'Add',
                    on_click=self.on_dataset_panel_add_button_clicked,
                    icon='add'
                ).props('flat color=primary')
                ui.button(
                    'Edit',
                    on_click=self.on_dataset_panel_edit_button_clicked,
                    icon='edit'
                ).props('flat color=secondary')
                ui.button(
                    'Remove',
                    on_click=self.on_dataset_panel_remove_button_clicked,
                    icon='delete'
                ).props('flat color=negative')

    def create_compute_panel(self):
        with ui.expansion('Model computation', icon='calculate', value=False).classes('w-full'):

            with ui.column().classes('w-full h-full p-4 min-w-0'):
                # Primary star parameters row
                with ui.row().classes('gap-4 items-center w-full mb-3') as self.compute_row_primary:
                    ui.label('Primary star:').classes('w-32 flex-shrink-0 text-sm font-medium')
                    self.parameters['atm@primary'] = PhoebeParameterWidget(
                        twig='atm@primary',
                        label='Model atmosphere',
                        api=self.phoebe_api
                    )

                    self.parameters['ntriangles@primary'] = PhoebeParameterWidget(
                        twig='ntriangles@primary',
                        label='Surface elements',
                        format='%d',
                        api=self.phoebe_api
                    )

                    self.parameters['distortion_method@primary'] = PhoebeParameterWidget(
                        twig='distortion_method@primary',
                        label='Distortion',
                        api=self.phoebe_api
                    )

                # Secondary star parameters row
                with ui.row().classes('gap-4 items-center w-full mb-3') as self.compute_row_secondary:
                    ui.label('Secondary star:').classes('w-32 flex-shrink-0 text-sm font-medium')
                    self.parameters['atm@secondary'] = PhoebeParameterWidget(
                        twig='atm@secondary',
                        label='Model atmosphere',
                        api=self.phoebe_api
                    )

                    self.parameters['ntriangles@secondary'] = PhoebeParameterWidget(
                        twig='ntriangles@secondary',
                        label='Surface elements',
                        format='%d',
                        api=self.phoebe_api
                    )

                    self.parameters['distortion_method@secondary'] = PhoebeParameterWidget(
                        twig='distortion_method@secondary',
                        label='Distortion',
                        api=self.phoebe_api
                    )

                # with ui.row().classes('gap-4 items-center w-full mb-3') as self.compute_row_envelope:
                #     ui.label('Envelope:').classes('w-32 flex-shrink-0 text-sm font-medium')

                #     self.parameters['ntriangles@envelope'] = PhoebeParameterWidget(
                #         twig='ntriangles@envelope',
                #         label='Surface elements',
                #         format='%d',
                #         api=self.phoebe_api
                #     )

                # System parameters and compute button row
                with ui.row().classes('gap-4 items-center w-full'):
                    self.parameters['irrad_method'] = PhoebeParameterWidget(
                        twig='irrad_method',
                        label='Irradiation method',
                        api=self.phoebe_api
                    )

                    self.parameters['dynamics_method'] = PhoebeParameterWidget(
                        twig='dynamics_method',
                        label='Dynamics method',
                        api=self.phoebe_api
                    )

                    self.parameters['boosting_method'] = PhoebeParameterWidget(
                        twig='boosting_method',
                        label='Boosting method',
                        api=self.phoebe_api
                    )

                    self.parameters['ltte'] = PhoebeParameterWidget(
                        twig='ltte',
                        label='Include LTTE',
                        api=self.phoebe_api
                    )
                    
                    self.compute_button = ui.button(
                        'Compute Model',
                        on_click=self.compute_model,
                        icon='calculate'
                    ).classes('h-12 flex-shrink-0')

    def create_lc_panel(self):
        with ui.expansion('Light curve', icon='insert_chart', value=False).classes('w-full'):

            with ui.column().classes('w-full h-full p-4 min-w-0'):

                # Plot controls row
                with ui.row().classes('gap-4 items-center mb-4'):
                    # X-axis dropdown
                    self.widgets['lc_plot_x_axis'] = ui.select(
                        options={'time': 'Time', 'phase': 'Phase'},
                        value='time',
                        label='X-axis'
                    ).classes('w-24 h-10')
                    self.widgets['lc_plot_x_axis'].on('update:model-value', lambda: self.on_lc_plot_update())

                    # Y-axis dropdown
                    self.widgets['lc_plot_y_axis'] = ui.select(
                        options={'magnitude': 'Magnitude', 'flux': 'Flux'},
                        value='flux',
                        label='Y-axis'
                    ).classes('w-24 h-10')
                    self.widgets['lc_plot_y_axis'].on('update:model-value', lambda: self.on_lc_plot_update())

                    # Plot button, styled for alignment
                    ui.button('Plot', on_click=self.on_lc_plot_button_clicked).classes('bg-blue-500 h-10 translate-y-4')

                # Plot container
                self.lc_canvas = ui.plotly(self.create_empty_styled_lc_plot()).classes('w-full  min-w-0')

                # Add resize observer to handle container size changes
                self.lc_canvas._props['config'] = {
                    'responsive': True,
                    'displayModeBar': True,
                    'displaylogo': False
                }

    def create_fitting_panel(self):
        with ui.expansion('Model fitting', icon='tune', value=False).classes('w-full'):

            with ui.column().classes('h-full p-4 min-w-0 w-full'):
                with ui.row().classes('gap-4 items-center w-full'):

                    # Solver selection
                    self.solver_select = ui.select(
                        options={'dc': 'Differential corrections'},
                        value='dc',
                        label='Solver'
                    ).classes('flex-1')

                    self.parameters['deriv_method@solver'] = PhoebeParameterWidget(
                        twig='deriv_method@solver',
                        label='Derivatives',
                        options=['symmetric', 'asymmetric'],
                        api=self.phoebe_api
                    )

                    self.parameters['expose_lnprobabilities@solver'] = PhoebeParameterWidget(
                        twig='expose_lnprobabilities@solver',
                        label='Expose ln-probabilities',
                        api=self.phoebe_api
                    )

                    self.fit_button = ui.button(
                        'Run solver',
                        on_click=self.run_solver,
                        icon='tune'
                    ).classes('h-12 flex-2')

                # Initialize empty table
                self.solution_table = ui.table(
                    columns=[
                        {'name': 'parameter', 'label': 'Adjusted Parameter', 'field': 'parameter', 'align': 'left'},
                        {'name': 'initial', 'label': 'Initial Value', 'field': 'initial', 'align': 'right'},
                        {'name': 'fitted', 'label': 'New Value', 'field': 'fitted', 'align': 'right'},
                        {'name': 'change_percent', 'label': 'Percent Change', 'field': 'change_percent', 'align': 'right'},
                    ],
                    rows=[],
                    row_key='parameter',
                ).classes('w-full').props('no-data-label="No parameters selected for adjustment."')

                # Adopt solution button (right-justified)
                with ui.row().classes('w-full justify-end mt-3'):
                    self.adopt_solution_button = ui.button(
                        'Adopt Solution',
                        icon='check_circle',
                        on_click=self.adopt_solver_solution
                    ).classes('bg-green-600 text-white px-6 py-2')

                    # disable it by default (no solution yet)
                    self.adopt_solution_button.props('disabled')

    def create_empty_styled_lc_plot(self):
        fig = go.Figure()

        x_title = 'Time (BJD)'
        y_title = 'Flux'

        fig.update_layout(
            xaxis_title=x_title,
            yaxis_title=y_title,
            hovermode='closest',
            template='plotly_white',
            autosize=True,
            height=400,
            margin=dict(l=50, r=50, t=50, b=50),
            xaxis=dict(
                mirror='allticks',
                ticks='outside',
                showline=True,
                linecolor='black',
                linewidth=2,
                zeroline=False,
                showgrid=True,
                gridcolor='lightgray',
                gridwidth=1,
                griddash='dot'
            ),
            yaxis=dict(
                mirror='allticks',
                ticks='outside',
                showline=True,
                linecolor='black',
                linewidth=2,
                # autorange='reversed' if y_reversed else True,
                zeroline=False,
                showgrid=True,
                gridcolor='lightgray',
                gridwidth=1,
                griddash='dot'
            ),
            plot_bgcolor='white',
            showlegend=False,
            uirevision=True
        )

        return fig

    def on_lc_plot_update(self):
        # Handle updates to the light curve plot
        return

    def on_lc_plot_button_clicked(self):
        # We'll redraw the figure from scratch each time.
        fig = self.create_empty_styled_lc_plot()

        period = self.parameters['period@binary@orbit@component'].get_value()
        t0 = self.parameters['t0_supconj@binary@orbit@component'].get_value()

        # See what needs to be plotted:
        for ds_label, ds_meta in self.dataset.datasets.items():
            if ds_meta['kind'] == 'lc':
                x_axis = self.widgets['lc_plot_x_axis'].value
                y_axis = self.widgets['lc_plot_y_axis'].value

                if ds_meta['plot_data']:
                    if x_axis == 'time':
                        xs = ds_meta['times']
                    else:
                        xs = time_to_phase(ds_meta['times'], period, t0)

                    if y_axis == 'flux':
                        ys = ds_meta['fluxes']
                    else:
                        ys = flux_to_magnitude(ds_meta['fluxes'])

                    data = np.column_stack((xs, ys))  # we could also add sigmas here

                    # Alias phases:
                    if x_axis == 'phase':
                        data = alias_data(data, extend_range=0.1)

                    fig.add_trace(go.Scatter(
                        x=data[:, 0],
                        y=data[:, 1],
                        mode='markers',
                        name=ds_label
                    ))

                if ds_meta['plot_model']:
                    if not ds_meta['model_fluxes']:
                        ui.notify(f'No model fluxes available for dataset {ds_label}. Please compute the model first.', type='warning')
                    compute_phases = np.linspace(ds_meta['phase_min'], ds_meta['phase_max'], ds_meta['n_points'])
                    if x_axis == 'time':
                        xs = t0 + period * compute_phases
                    else:
                        xs = compute_phases

                    if y_axis == 'flux':
                        ys = ds_meta['model_fluxes']
                    else:
                        ys = flux_to_magnitude(ds_meta['model_fluxes'])

                    model = np.column_stack((xs, ys))

                    if x_axis == 'phase':
                        model = alias_data(model, extend_range=0.1)

                    fig.add_trace(go.Scatter(
                        x=model[:, 0],
                        y=model[:, 1],
                        mode='lines',
                        line={'color': 'red'},
                        name=ds_label
                    ))

        self.lc_canvas.figure = fig
        self.lc_canvas.update()

    def create_analysis_panel(self):
        with ui.column().classes('w-full h-full p-4 min-w-0'):
            # Dataset management panel:
            self.dataset.mount_panel()

            # Compute management panel:
            self.create_compute_panel()

            # Light curve plot (pass reference to UI for parameter access)
            self.create_lc_panel()

            # Fitting panel:
            self.create_fitting_panel()

    def show_startup_dialog(self):
        """Show startup dialog to collect user info and initialize session."""
        with ui.dialog().props('persistent') as self.startup_dialog, ui.card().classes('w-96'):
            ui.label('Welcome to Phoebe Lab UI').classes('text-xl font-bold mb-4')

            # Show client ID (will be populated after session init)
            ui.label('Session ID:').classes('text-sm font-medium')
            self.client_id_display = ui.label('Initializing...').classes('text-sm text-gray-600 mb-4 font-mono')

            ui.separator().classes('my-4')

            # User info form
            ui.label('Please provide your information:').classes('text-sm font-medium mb-2')

            self.first_name_input = ui.input(
                label='First Name',
                placeholder='Enter your first name'
            ).classes('mb-2').props('outlined')

            self.last_name_input = ui.input(
                label='Last Name',
                placeholder='Enter your last name'
            ).classes('mb-4').props('outlined')

            # Buttons
            with ui.row().classes('gap-2 justify-end w-full'):
                ui.button('Continue', on_click=self._on_continue_startup).classes('bg-blue-500').props('unelevated')

        # Open dialog and initialize session
        self.startup_dialog.open()
        self._initialize_session_background()

    def _initialize_session_background(self):
        """Initialize session in the background."""
        # Prevent duplicate session creation
        if self.client_id:
            self.client_id_display.text = self.client_id
            return

        if not self.session_api:
            self.client_id_display.text = 'API not available'
            return

        try:
            # Start a new session
            response = self.session_api.start_session()
            self.client_id = response.get('client_id')

            if self.client_id and self.phoebe_api:
                # Set client ID in Phoebe API
                self.phoebe_api.set_client_id(self.client_id)
                self.client_id_display.text = self.client_id
            else:
                self.client_id_display.text = 'Failed to initialize'

        except Exception as e:
            self.client_id_display.text = f'Error: {str(e)}'

    def _on_continue_startup(self):
        """Handle continue button in startup dialog."""
        first_name = self.first_name_input.value.strip()
        last_name = self.last_name_input.value.strip()

        if not first_name or not last_name:
            ui.notify('Please enter both first and last name', type='warning')
            return

        if not self.client_id:
            ui.notify('Session not ready. Please wait and try again.', type='warning')
            return

        # Store user info
        self.user_first_name = first_name
        self.user_last_name = last_name

        # Update session metadata with user info
        try:
            self.session_api.update_user_info(self.client_id, first_name, last_name)
        except Exception as e:
            ui.notify(f'Warning: Could not update session info: {str(e)}', type='warning')

        # Close dialog and show main UI
        self.startup_dialog.close()
        self.main_splitter.style('display: flex')

        ui.notify(f'Welcome {first_name} {last_name}! Session {self.client_id} ready.', type='positive')

    def cleanup_session(self):
        """Cleanup the current session."""
        if self.client_id and self.session_api:
            try:
                self.session_api.end_session(self.client_id)
                print(f"[phoebe_ui] Session {self.client_id} ended cleanly.")
            except Exception as e:
                print(f"[phoebe_ui] Error ending session: {e}")
            finally:
                self.client_id = None
                if self.phoebe_api:
                    self.phoebe_api.set_client_id(None)

    def on_ephemeris_changed(self, param_name=None, param_value=None):
        """Handle changes to ephemeris parameters (t0, period) and update phase plot."""
        # Only replot if we're currently showing phase on x-axis or if there's any data to plot
        if self.widgets['lc_plot_x_axis'].value == 'phase' or any(
            ds_meta.get('plot_data', False) or ds_meta.get('plot_model', False)
            for ds_meta in self.dataset.datasets.values() if ds_meta['kind'] == 'lc'
        ):
            self.on_lc_plot_button_clicked()

    def sync_ui_state(self, *args, **kwargs):
        """Sync UI state with backend Phoebe API."""
        if not self.phoebe_api:
            return

        # Prevent recursive calls
        if hasattr(self, '_sync_in_progress') and self._sync_in_progress:
            return

        self._sync_in_progress = True
        try:
            # Sync all parameters
            for param_widget in self.parameters.values():
                try:
                    param_widget.update_uniqueid()
                    # Skip if parameter doesn't exist in backend (e.g., UI-only parameters in loaded bundles)
                    if param_widget.uniqueid is None:
                        continue
                    value_from_bundle = self.phoebe_api.get_value(uniqueid=param_widget.uniqueid)['result']
                    param_widget.set_value(value_from_bundle)
                except Exception as e:
                    # Skip parameters that don't exist in the loaded bundle
                    print(f"Warning: Could not sync parameter {param_widget.twig}: {e}")
                    continue

            # Sync datasets from bundle and refresh UI
            try:
                self.dataset.sync_from_bundle()
                self.dataset.refresh()
            except Exception as e:
                import traceback
                traceback.print_exc()
                ui.notify(f"Failed to sync datasets from bundle: {str(e)}", type='warning')
        finally:
            self._sync_in_progress = False

    def update_morphology(self, new_morphology):
        # change morphology in the backend:
        self.phoebe_api.change_morphology(new_morphology)

        # cycle through all phoebe parameters defined in the UI:
        for param_widget in self.parameters.values():
            # update parameter uniqueids:
            param_widget.update_uniqueid()

            # disable parameters if they're constrained:
            response = self.phoebe_api.is_parameter_constrained(uniqueid=param_widget.uniqueid)
            if response['success']:
                constrained = response['result']
                param_widget.set_visible(not constrained)
            else:
                ui.notify(f"Failed to check if parameter {param_widget.twig} is constrained", type='negative')

            # update the value:
            if not constrained:
                param_widget.on_value_changed(event=False)

        # Readd all datasets:
        self.dataset.readd_all()

    async def _confirm_morphology_change(self, dialog, new_morphology):
        self.morph_confirm_btn.props('loading')

        try:
            await get_event_loop().run_in_executor(
                None, self.update_morphology, new_morphology
            )
        finally:
            self.morph_confirm_btn.props(remove='loading')

        dialog.close()

        ui.notify(f'Morphology changed to {new_morphology}.', type='positive')

    async def compute_model(self):
        """Compute Phoebe model with current parameters."""
        try:
            # Show button loading indicator
            self.compute_button.props('loading')

            # Run the compute operation asynchronously to avoid blocking the UI
            response = await get_event_loop().run_in_executor(
                None, self.phoebe_api.run_compute
            )

            if response.get('success', False):
                model_data = response.get('result', {}).get('model', {})

                for ds_label, ds_meta in self.dataset.datasets.items():
                    if ds_label in model_data:
                        ds_data = model_data[ds_label]
                        ds_meta['model_fluxes'] = ds_data.get('fluxes', [])
                        ds_meta['model_rv1s'] = ds_data.get('rv1s', [])
                        ds_meta['model_rv2s'] = ds_data.get('rv2s', [])
                    else:
                        ds_meta['model_fluxes'] = []
                        ds_meta['model_rv1s'] = []
                        ds_meta['model_rv2s'] = []
                
                ui.notify('Model computed successfully!', type='positive')
            else:
                ui.notify(f"Model computation failed: {response.get('error', 'Unknown error')}", type='negative')

        except Exception as e:
            ui.notify(f"Error computing model: {str(e)}", type='negative')
        finally:
            # Remove button loading indicator
            self.compute_button.props(remove='loading')

    async def run_solver(self):
        fit_parameters = [twig for twig, parameter in self.parameters.items() if hasattr(parameter, 'adjust') and parameter.adjust]
        if not fit_parameters:
            ui.notify('No parameters selected for fitting', type='warning')
            return

        steps = [self.parameters[twig].step for twig in fit_parameters]

        self.phoebe_api.set_value(twig='fit_parameters@solver', value=fit_parameters)
        self.phoebe_api.set_value(twig='steps@solver', value=steps)

        try:
            # Show button loading indicator
            self.fit_button.props('loading')

            # Run the compute operation asynchronously to avoid blocking the UI
            response = await get_event_loop().run_in_executor(
                None, self.phoebe_api.run_solver
            )

            if response.get('success', False):
                solution_data = response.get('result', {}).get('solution', {})

                # Update the solver results table
                self.update_solution_table(solution_data)

                # Enable adopt solution button:
                self.adopt_solution_button.props(remove='disabled')

                ui.notify("Model fitting succeeded", type='positive')
            else:
                ui.notify(f"Model fitting failed: {response.get('error', 'Unknown error')}", type='negative')

        except Exception as e:
            ui.notify(f"Error fitting parameters: {str(e)}", type='negative')
        finally:
            # Remove button loading indicator
            self.fit_button.props(remove='loading')

    def update_solution_table(self, solution_data):
        """Update the solver results table with the fitting results."""

        # Extract solution data
        fit_parameters = solution_data.get('fit_parameters')
        initial_values = solution_data.get('initial_values')
        fitted_values = solution_data.get('fitted_values')

        # Prepare table data
        table_data = []
        for i, param in enumerate(fit_parameters):
            initial_val = initial_values[i]
            fitted_val = fitted_values[i]

            # Calculate percentage change
            if initial_val != 0:
                percent_change = ((fitted_val - initial_val) / initial_val) * 100
                percent_change_str = f'{percent_change:+.2f}%'
            else:
                percent_change_str = 'N/A'

            table_data.append({
                'parameter': param,
                'initial': f'{initial_val:.6f}',
                'fitted': f'{fitted_val:.6f}',
                'change_percent': percent_change_str
            })

        # Update the table
        self.solution_table.rows = table_data
        self.solution_table.update()

    def add_parameter_to_solver_table(self, par):
        rows = list(self.solution_table.rows)
        twig = par.get_twig()

        # only add a parameter if it's not already in the table:
        if not any(row['parameter'] == twig for row in rows):
            row_data = {
                'parameter': twig,
                'initial': par.get_value(),
                'fitted': 'n/a',
                'change_percent': 'n/a'
            }

            rows.append(row_data)
            self.solution_table.rows = rows
            self.solution_table.update()

    def remove_parameter_from_solver_table(self, par):
        twig = par.get_twig()
        rows = [row for row in self.solution_table.rows if row['parameter'] != twig]
        self.solution_table.rows = rows
        self.solution_table.update()

    def update_parameters_in_solver_table(self):
        rows = list(self.solution_table.rows)

        for i, row in enumerate(rows):
            par = self.parameters[row['parameter']]
            rows[i]['initial'] = par.get_value()
            rows[i]['fitted'] = 'n/a'
            rows[i]['change_percent'] = 'n/a'

        self.solution_table.rows = rows
        self.solution_table.update()

    def adopt_solver_solution(self):
        """Adopt the solver solution by setting fitted values to current parameters."""
        try:
            # Get all rows from the solution table
            for row in self.solution_table.rows:
                twig = row['parameter']
                fitted_value = row.get('fitted', 'n/a')

                # Skip if no fitted value available
                if fitted_value == 'n/a' or fitted_value is None:
                    continue

                # Set the parameter value
                param_widget = self.parameters[twig]
                param_widget.set_value(fitted_value)
                param_widget.on_value_changed(event=False)

            # Update the solution table to reflect the adopted values
            self.update_parameters_in_solver_table()

            # Clear model data since parameters have changed
            for ds_label, ds_meta in self.dataset.datasets.items():
                ds_meta['model_fluxes'] = []
                ds_meta['model_rv1s'] = []
                ds_meta['model_rv2s'] = []

            # Disable adopt solution button:
            self.adopt_solution_button.props('disabled')
        except Exception as e:
            ui.notify(f'Error adopting solver solution: {str(e)}', type='negative')

    async def on_load_model(self):
        """Load model from file with browser upload and confirmation dialog."""
        # Create a dialog to warn about unsaved changes and upload file

        with ui.dialog() as dialog, ui.card():
            ui.label('Load Model').classes('text-h6')
            ui.label('Warning: Loading a bundle will discard any unsaved changes to the current model.').classes('text-orange-600 mb-4')

            # File upload widget for selecting bundle file
            ui.upload(
                label='Select a phoebe model to upload',
                on_upload=lambda e: self.load_bundle_from_upload(e, dialog),
                auto_upload=True
            ).classes('w-full mb-4')

            with ui.row().classes('w-full justify-end gap-2 mt-4'):
                ui.button('Cancel', on_click=dialog.close).props('flat')

        dialog.open()

    async def load_bundle_from_upload(self, event, dialog):
        """Load the bundle file from uploaded content."""
        try:
            # Show loading indicator
            self.load_button.props('loading')

            # Get the uploaded file content
            filename = event.name
            file_content = event.content.read()

            response = await get_event_loop().run_in_executor(
                None,
                lambda: self.phoebe_api.load_bundle(bundle=file_content.decode('utf-8'))
            )

            if response.get('success', False):
                ui.notify(f'Bundle loaded from {filename}', type='positive')
                dialog.close()

                # Sync UI state with the loaded model
                self.sync_ui_state()
            else:
                ui.notify(f"Failed to load bundle: {response.get('error', 'Unknown error')}", type='negative')

        except Exception as e:
            ui.notify(f'Error loading bundle: {str(e)}', type='negative')

        finally:
            self.load_button.props(remove='loading')

    async def on_save_model(self):
        """Save model and trigger browser download."""
        try:
            # Show loading indicator
            self.save_button.props('loading')

            # Call API to get bundle content:
            response = await get_event_loop().run_in_executor(
                None, self.phoebe_api.save_bundle
            )

            if response.get('success', False):
                # Get the bundle content from the response (may be wrapped in 'result')
                result = response.get('result', response)
                bundle = result.get('bundle', '')

                if bundle:
                    # Trigger browser download
                    ui.download(bundle.encode('utf-8'), 'bundle.phoebe')
                    ui.notify('Bundle downloaded successfully', type='positive')
                else:
                    ui.notify('Bundle content is empty', type='warning')
            else:
                ui.notify(f"Failed to save bundle: {response.get('error', 'Unknown error')}", type='negative')

        except Exception as e:
            ui.notify(f'Error saving bundle: {str(e)}', type='negative')

        finally:
            self.save_button.props(remove='loading')

    def get_user_info(self):
        """Get user information for logging or display purposes."""
        if self.user_first_name and self.user_last_name:
            return f"{self.user_first_name} {self.user_last_name}"
        return "Unknown User"

    def get_session_info(self):
        """Get session information for logging or display purposes."""
        return {
            'client_id': self.client_id,
            'user_name': self.get_user_info(),
            'session_active': bool(self.client_id)
        }


@ui.page('/')
def main_page(client: Client):
    # Initialize API clients
    session_api = SessionAPI(base_url="http://localhost:8001")
    phoebe_api = PhoebeAPI(base_url="http://localhost:8001")

    # Create UI with API instances for this connected client
    app = PhoebeUI(session_api=session_api, phoebe_api=phoebe_api)
    client.on_disconnect(app.cleanup_session)


if __name__ in {"__main__", "__mp_main__"}:
    ui.run(host='0.0.0.0', port=8082, title='PHOEBE Lab UI', reload=False)
