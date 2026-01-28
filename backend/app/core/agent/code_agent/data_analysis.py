#!/usr/bin/env python
# coding=utf-8
"""
Data Analysis Presets for CodeAgent.

This module provides pre-configured tools and helpers for data analysis
tasks, including pandas, numpy, visualization, and machine learning.
"""

from typing import Any, Callable

# ============================================================================
# Data Analysis Module Lists
# ============================================================================

# Core data analysis modules
CORE_DATA_MODULES = [
    "pandas",
    "numpy",
]

# Visualization modules
VISUALIZATION_MODULES = [
    "matplotlib",
    "matplotlib.pyplot",
    "seaborn",
    "plotly",
    "plotly.express",
    "plotly.graph_objects",
]

# Machine learning modules
ML_MODULES = [
    "sklearn",
    "sklearn.model_selection",
    "sklearn.preprocessing",
    "sklearn.linear_model",
    "sklearn.tree",
    "sklearn.ensemble",
    "sklearn.cluster",
    "sklearn.metrics",
    "sklearn.neighbors",
    "sklearn.svm",
    "sklearn.naive_bayes",
    "sklearn.decomposition",
    "sklearn.pipeline",
]

# Statistics modules
STATISTICS_MODULES = [
    "scipy",
    "scipy.stats",
    "scipy.optimize",
    "scipy.signal",
    "scipy.interpolate",
    "statsmodels",
    "statsmodels.api",
    "statsmodels.formula.api",
]

# Data I/O modules
DATA_IO_MODULES = [
    "csv",
    "openpyxl",
    "xlrd",
    "xlwt",
    "json",
    "pickle",  # Note: pickle is dangerous for untrusted data
]

# All data analysis modules combined
ALL_DATA_ANALYSIS_MODULES = (
    CORE_DATA_MODULES + VISUALIZATION_MODULES + ML_MODULES + STATISTICS_MODULES + DATA_IO_MODULES
)


# ============================================================================
# Built-in Helper Functions
# ============================================================================


def create_data_analysis_tools() -> dict[str, Callable[..., Any]]:
    """
    Create built-in helper tools for data analysis.

    Returns:
        Dictionary of tool name -> function.
    """
    tools: dict[str, Callable[..., Any]] = {}

    def describe_dataframe(df) -> str:
        """
        Get a comprehensive description of a pandas DataFrame.

        Args:
            df: A pandas DataFrame to describe.

        Returns:
            Formatted string with shape, columns, dtypes, sample, and statistics.
        """
        try:
            import io

            buffer = io.StringIO()

            buffer.write("=== DataFrame Overview ===\n")
            buffer.write(f"Shape: {df.shape} ({df.shape[0]} rows × {df.shape[1]} columns)\n\n")

            buffer.write("=== Columns and Types ===\n")
            for col in df.columns:
                dtype = df[col].dtype
                null_count = df[col].isnull().sum()
                unique_count = df[col].nunique()
                buffer.write(f"  {col}: {dtype} (nulls: {null_count}, unique: {unique_count})\n")

            buffer.write("\n=== Sample Data (first 5 rows) ===\n")
            buffer.write(df.head().to_string())

            buffer.write("\n\n=== Numeric Statistics ===\n")
            numeric_df = df.select_dtypes(include=["number"])
            if not numeric_df.empty:
                buffer.write(numeric_df.describe().to_string())
            else:
                buffer.write("No numeric columns")

            return buffer.getvalue()
        except Exception as e:
            return f"Error describing DataFrame: {e}"

    tools["describe_dataframe"] = describe_dataframe

    def save_figure(fig, filename: str, dpi: int = 150) -> str:
        """
        Save a matplotlib figure to file.

        Args:
            fig: Matplotlib figure object.
            filename: Name for the saved file.
            dpi: Resolution in dots per inch.

        Returns:
            Path to the saved file.
        """
        try:
            import os

            output_dir = "/tmp/plots"
            os.makedirs(output_dir, exist_ok=True)

            filepath = os.path.join(output_dir, filename)
            fig.savefig(filepath, dpi=dpi, bbox_inches="tight")

            return f"Figure saved to: {filepath}"
        except Exception as e:
            return f"Error saving figure: {e}"

    tools["save_figure"] = save_figure

    def analyze_correlation(df, method: str = "pearson") -> str:
        """
        Analyze correlations between numeric columns.

        Args:
            df: A pandas DataFrame.
            method: Correlation method ('pearson', 'spearman', 'kendall').

        Returns:
            Formatted correlation matrix and top correlations.
        """
        try:
            import io

            buffer = io.StringIO()

            numeric_df = df.select_dtypes(include=["number"])
            if numeric_df.empty:
                return "No numeric columns for correlation analysis"

            corr = numeric_df.corr(method=method)

            buffer.write(f"=== Correlation Matrix ({method}) ===\n")
            buffer.write(corr.to_string())

            # Find top correlations
            buffer.write("\n\n=== Top Correlations ===\n")
            pairs = []
            for i in range(len(corr.columns)):
                for j in range(i + 1, len(corr.columns)):
                    col1, col2 = corr.columns[i], corr.columns[j]
                    corr_val = corr.iloc[i, j]
                    pairs.append((col1, col2, corr_val))

            pairs.sort(key=lambda x: abs(x[2]), reverse=True)
            for col1, col2, corr_val in pairs[:10]:
                buffer.write(f"  {col1} <-> {col2}: {corr_val:.4f}\n")

            return buffer.getvalue()
        except Exception as e:
            return f"Error analyzing correlation: {e}"

    tools["analyze_correlation"] = analyze_correlation

    def detect_outliers(df, column: str, method: str = "iqr") -> str:
        """
        Detect outliers in a numeric column.

        Args:
            df: A pandas DataFrame.
            column: Column name to analyze.
            method: Detection method ('iqr', 'zscore').

        Returns:
            Summary of detected outliers.
        """
        try:
            import io

            import numpy as np

            buffer = io.StringIO()

            if column not in df.columns:
                return f"Column '{column}' not found"

            data = df[column].dropna()

            if method == "iqr":
                Q1 = data.quantile(0.25)
                Q3 = data.quantile(0.75)
                IQR = Q3 - Q1
                lower = Q1 - 1.5 * IQR
                upper = Q3 + 1.5 * IQR
                outliers = data[(data < lower) | (data > upper)]
            elif method == "zscore":
                z_scores = np.abs((data - data.mean()) / data.std())
                outliers = data[z_scores > 3]
            else:
                return f"Unknown method: {method}"

            buffer.write(f"=== Outlier Detection ({method}) for '{column}' ===\n")
            buffer.write(f"Total values: {len(data)}\n")
            buffer.write(f"Outliers found: {len(outliers)} ({len(outliers) / len(data) * 100:.2f}%)\n")

            if len(outliers) > 0:
                buffer.write("\nOutlier statistics:\n")
                buffer.write(f"  Min outlier: {outliers.min():.4f}\n")
                buffer.write(f"  Max outlier: {outliers.max():.4f}\n")
                buffer.write(f"  Mean outlier: {outliers.mean():.4f}\n")

            if method == "iqr":
                buffer.write(f"\nIQR bounds: [{lower:.4f}, {upper:.4f}]\n")

            return buffer.getvalue()
        except Exception as e:
            return f"Error detecting outliers: {e}"

    tools["detect_outliers"] = detect_outliers

    def quick_eda(df, max_cols: int = 20) -> str:
        """
        Perform quick exploratory data analysis on a DataFrame.

        Args:
            df: A pandas DataFrame.
            max_cols: Maximum columns to analyze in detail.

        Returns:
            Comprehensive EDA report.
        """
        try:
            import io

            buffer = io.StringIO()

            buffer.write("=" * 60 + "\n")
            buffer.write("           EXPLORATORY DATA ANALYSIS REPORT\n")
            buffer.write("=" * 60 + "\n\n")

            # Basic info
            buffer.write("=== Basic Information ===\n")
            buffer.write(f"Rows: {df.shape[0]}\n")
            buffer.write(f"Columns: {df.shape[1]}\n")
            buffer.write(f"Memory usage: {df.memory_usage(deep=True).sum() / 1024**2:.2f} MB\n")
            buffer.write(f"Duplicate rows: {df.duplicated().sum()}\n\n")

            # Missing values
            buffer.write("=== Missing Values ===\n")
            missing = df.isnull().sum()
            missing_pct = (missing / len(df) * 100).round(2)
            for col in missing[missing > 0].index:
                buffer.write(f"  {col}: {missing[col]} ({missing_pct[col]}%)\n")
            if missing.sum() == 0:
                buffer.write("  No missing values!\n")
            buffer.write("\n")

            # Data types
            buffer.write("=== Data Types ===\n")
            for dtype, count in df.dtypes.value_counts().items():
                buffer.write(f"  {dtype}: {count} columns\n")
            buffer.write("\n")

            # Numeric summary
            numeric_cols = df.select_dtypes(include=["number"]).columns[:max_cols]
            if len(numeric_cols) > 0:
                buffer.write("=== Numeric Columns Summary ===\n")
                buffer.write(df[numeric_cols].describe().to_string())
                buffer.write("\n\n")

            # Categorical summary
            cat_cols = df.select_dtypes(include=["object", "category"]).columns[:max_cols]
            if len(cat_cols) > 0:
                buffer.write("=== Categorical Columns Summary ===\n")
                for col in cat_cols:
                    n_unique = df[col].nunique()
                    top_values = df[col].value_counts().head(5)
                    buffer.write(f"\n{col} (unique: {n_unique}):\n")
                    for val, count in top_values.items():
                        buffer.write(f"  {val}: {count} ({count / len(df) * 100:.1f}%)\n")

            return buffer.getvalue()
        except Exception as e:
            return f"Error performing EDA: {e}"

    tools["quick_eda"] = quick_eda

    def create_train_test_split(
        df,
        target_column: str,
        test_size: float = 0.2,
        random_state: int = 42,
    ) -> dict:
        """
        Split DataFrame into train and test sets.

        Args:
            df: A pandas DataFrame.
            target_column: Name of the target column.
            test_size: Fraction of data for testing.
            random_state: Random seed for reproducibility.

        Returns:
            Dictionary with X_train, X_test, y_train, y_test.
        """
        try:
            from sklearn.model_selection import train_test_split

            if target_column not in df.columns:
                raise ValueError(f"Target column '{target_column}' not found")

            X = df.drop(columns=[target_column])
            y = df[target_column]

            X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=test_size, random_state=random_state)

            return {
                "X_train": X_train,
                "X_test": X_test,
                "y_train": y_train,
                "y_test": y_test,
                "info": f"Train: {len(X_train)} samples, Test: {len(X_test)} samples",
            }
        except Exception as e:
            return {"error": str(e)}

    tools["create_train_test_split"] = create_train_test_split

    return tools


# ============================================================================
# Preset Configurations
# ============================================================================


class DataAnalysisPreset:
    """
    Preset configuration for data analysis CodeAgent.
    """

    def __init__(
        self,
        enable_visualization: bool = True,
        enable_ml: bool = True,
        enable_statistics: bool = True,
    ):
        """
        Initialize data analysis preset.

        Args:
            enable_visualization: Enable visualization modules.
            enable_ml: Enable machine learning modules.
            enable_statistics: Enable statistics modules.
        """
        self.enable_visualization = enable_visualization
        self.enable_ml = enable_ml
        self.enable_statistics = enable_statistics

    def get_authorized_imports(self) -> list[str]:
        """Get list of authorized imports for this preset."""
        imports = list(CORE_DATA_MODULES)

        if self.enable_visualization:
            imports.extend(VISUALIZATION_MODULES)

        if self.enable_ml:
            imports.extend(ML_MODULES)

        if self.enable_statistics:
            imports.extend(STATISTICS_MODULES)

        imports.extend(DATA_IO_MODULES)

        return imports

    def get_tools(self) -> dict[str, Callable]:
        """Get helper tools for this preset."""
        return create_data_analysis_tools()

    def get_install_packages(self) -> list[str]:
        """Get pip packages to install for Docker executor."""
        packages = ["pandas", "numpy"]

        if self.enable_visualization:
            packages.extend(["matplotlib", "seaborn", "plotly"])

        if self.enable_ml:
            packages.append("scikit-learn")

        if self.enable_statistics:
            packages.extend(["scipy", "statsmodels"])

        return packages


# Common presets
PRESET_BASIC = DataAnalysisPreset(
    enable_visualization=False,
    enable_ml=False,
    enable_statistics=False,
)

PRESET_VISUALIZATION = DataAnalysisPreset(
    enable_visualization=True,
    enable_ml=False,
    enable_statistics=False,
)

PRESET_ML = DataAnalysisPreset(
    enable_visualization=True,
    enable_ml=True,
    enable_statistics=False,
)

PRESET_FULL = DataAnalysisPreset(
    enable_visualization=True,
    enable_ml=True,
    enable_statistics=True,
)


def get_preset(name: str) -> DataAnalysisPreset:
    """
    Get a data analysis preset by name.

    Args:
        name: Preset name ('basic', 'visualization', 'ml', 'full').

    Returns:
        DataAnalysisPreset instance.
    """
    presets = {
        "basic": PRESET_BASIC,
        "visualization": PRESET_VISUALIZATION,
        "ml": PRESET_ML,
        "full": PRESET_FULL,
    }

    return presets.get(name.lower(), PRESET_FULL)


__all__ = [
    # Module lists
    "CORE_DATA_MODULES",
    "VISUALIZATION_MODULES",
    "ML_MODULES",
    "STATISTICS_MODULES",
    "DATA_IO_MODULES",
    "ALL_DATA_ANALYSIS_MODULES",
    # Tools
    "create_data_analysis_tools",
    # Presets
    "DataAnalysisPreset",
    "PRESET_BASIC",
    "PRESET_VISUALIZATION",
    "PRESET_ML",
    "PRESET_FULL",
    "get_preset",
]
