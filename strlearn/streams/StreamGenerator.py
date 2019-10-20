"""
Data streams generator.

A class for generating streams with various parameters.
"""

from sklearn.datasets import make_classification
import numpy as np
from scipy.stats import logistic


class StreamGenerator:
    """
    Data streams generator for both stationary
    and drifting data streams.

    Parameters
    ----------
    n_chunks : integer, optional (default=250)
        The number of data chunks, that the stream
        is composed of.
    chunk_size : integer, optional (default=200)
        The number of instances in each data chunk.
    random_state : integer, optional (default=1410)
        The seed used by the random number generator.
    n_drifts : integer, optional (default=4)
        The number of concept changes in the data stream.
    concept_sigmoid_spacing : float, optional (default=10.)
        Value that determines how sudden is the change of concept.
        The higher the value, the more sudden the drift is.
    n_classes : integer, optional (default=2)
        The number of classes in the generated data stream.
    weights : jeśli krotka to zmienny w czasie (temporalny?), jeśli cokolwiek innego, to wektor wag działający jak przekazywany bezpośrednio do make_classification. W wypadku krotki przepuszczamy jedynie problemy binarne.

    elementy krotki to:
    - liczba dryfów
    - sigmoid spacing dla dryfu wag (zakładamy)
    - wartość z przedziału 0-1 określająca amplitudę zmian balansu oscylującego wokół stanu równowagi klas

    Attributes
    ----------

    """

    def __init__(
        self,
        n_chunks=250,
        chunk_size=200,
        random_state=1410,
        n_drifts=0,
        concept_sigmoid_spacing=None,
        n_classes=2,
        reocurring=False,
        weights=None,
        **kwargs,
    ):
        # Wyższy spacing, bardziej nagły
        self.n_chunks = n_chunks
        self.chunk_size = chunk_size
        self.random_state = random_state
        self.n_drifts = n_drifts
        self.concept_sigmoid_spacing = concept_sigmoid_spacing
        self.n_classes = n_classes
        self.make_classification_kwargs = kwargs
        self.reocurring = reocurring
        self.n_samples = self.n_chunks * self.chunk_size
        self.weights = weights
        self.classes = [label for label in range(self.n_classes)]

    def is_dry(self):
        """Checking if we have reached the end of the stream."""

        return (
            self.chunk_id + 1 >= self.n_chunks if hasattr(self, "chunk_id") else False
        )

    def _sigmoid(self, sigmoid_spacing, n_drifts):
        period = (
            int((self.n_samples) / (n_drifts)) if n_drifts > 0 else int(self.n_samples)
        )
        css = sigmoid_spacing if sigmoid_spacing is not None else 9999
        probabilities = (
            logistic.cdf(
                np.concatenate(
                    [
                        np.linspace(
                            -css if i % 2 else css, css if i % 2 else -css, period
                        )
                        for i in range(n_drifts)
                    ]
                )
            )
            if n_drifts > 0
            else np.ones(self.n_samples)
        )

        return (period, probabilities)

    def get_chunk(self):
        """
        Generating a data chunk of a stream.

        Returns
        -------
        current_chunk : tuple {array-like, shape (n_samples, n_features),
        array-like, shape (n_samples, )}
            Generated samples and target values.
        """
        if hasattr(self, "X"):
            self.previous_chunk = self.current_chunk
        else:
            # To jest dziwna koncepcja z wagami z wierszy macierzy diagonalnej ale działa.
            # Jak coś działa to jest dobre.
            self.concepts = np.array(
                [
                    [
                        make_classification(
                            **self.make_classification_kwargs,
                            n_samples=self.n_chunks * self.chunk_size,
                            n_classes=self.n_classes,
                            random_state=self.random_state + i,
                            weights=weights.tolist(),
                        )[0].T
                        for weights in np.diag(
                            np.diag(np.ones((self.n_classes, self.n_classes)))
                        )
                    ]
                    for i in range(self.n_drifts + 1 if not self.reocurring else 2)
                ]
            )

            # Prepare concept sigmoids if there are drifts
            if self.n_drifts > 0:
                # Get period and probabilities
                period, self.concept_probabilities = self._sigmoid(
                    self.concept_sigmoid_spacing, self.n_drifts
                )

                # Szum
                self.concept_noise = np.random.rand(self.n_samples)

                # Selekcja klas
                self.concept_selector = (
                    self.concept_probabilities < self.concept_noise
                ).astype(int)

                # Reocurring drift
                if self.reocurring == False:
                    for i in range(1, self.n_drifts):
                        start, end = (i * period, (i + 1) * period)
                        self.concept_selector[
                            np.where(self.concept_selector[start:end] == 1)[0] + start
                        ] = i + ((i + 1) % 2)
                        self.concept_selector[
                            np.where(self.concept_selector[start:end] == 0)[0] + start
                        ] = i + (i % 2)

            # Selekcja klas na potrzeby doboru balansu
            self.balance_noise = np.random.rand(self.n_samples)

            # Case of same size of all classes
            if self.weights is None:
                self.class_selector = (self.balance_noise * self.n_classes).astype(int)
            # If static balance is given
            elif not isinstance(self.weights, tuple):
                self.class_selector = np.zeros(self.balance_noise.shape).astype(int)
                accumulator = 0.0
                for i, treshold in enumerate(self.weights):
                    mask = self.balance_noise > accumulator
                    self.class_selector[mask] = i
                    accumulator += treshold
            # If dynamic balance is given
            else:
                self.n_balance_drifts, self.class_sigmoid_spacing, self.balance_amplitude = (
                    self.weights
                )

                period, self.class_probabilities = self._sigmoid(
                    self.class_sigmoid_spacing, self.n_balance_drifts
                )

                # Amplitude correction
                self.class_probabilities -= 0.5
                self.class_probabilities *= self.balance_amplitude
                self.class_probabilities += 0.5

                # Will it work?
                self.class_selector = (
                    self.class_probabilities < self.balance_noise
                ).astype(int)

            # Przypisanie klas i etykiet
            if self.n_drifts > 0:
                # Jeśli dryfy, przypisz koncepty
                self.concepts = np.choose(self.concept_selector, self.concepts)
            else:
                # Jeśli nie, przecież jest jeden, więc spłaszcz
                self.concepts = np.squeeze(self.concepts)

            self.X = np.choose(self.class_selector, self.concepts).T
            self.y = self.class_selector

            self.chunk_id = -1
            self.previous_chunk = None

        self.chunk_id += 1

        if self.chunk_id < self.n_chunks:
            start, end = (
                self.chunk_size * self.chunk_id,
                self.chunk_size * self.chunk_id + self.chunk_size,
            )

            self.current_chunk = (self.X[start:end], self.y[start:end])
            return self.current_chunk
        else:
            return None