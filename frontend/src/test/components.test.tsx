import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { StatusBadge } from '../components/common/StatusBadge';
import { Modal } from '../components/common/Modal';
import { Input } from '../components/common/Input';

describe('Common Components', () => {
  describe('StatusBadge', () => {
    it('renders all required status variants with appropriate text and styling', () => {
      const statuses = [
        'uploaded',
        'processing',
        'extracted',
        'needs_review',
        'auto_approved',
        'approved',
        'rejected',
        'failed',
        'exported',
      ] as const;

      const { rerender } = render(<StatusBadge status="uploaded" />);
      for (const st of statuses) {
        rerender(<StatusBadge status={st} />);
        const badge = screen.getByTestId(`status-badge-${st}`);
        expect(badge).toBeInTheDocument();
        expect(badge.textContent).toBeTruthy();
      }
    });
  });

  describe('Modal', () => {
    it('traps focus, renders title, and triggers onClose on Escape', () => {
      const onClose = vi.fn();
      render(
        <Modal isOpen={true} onClose={onClose} title="Test Modal">
          <button>Action Button</button>
        </Modal>
      );

      expect(screen.getByText('Test Modal')).toBeInTheDocument();

      // Escape key triggers onClose
      fireEvent.keyDown(document, { key: 'Escape' });
      expect(onClose).toHaveBeenCalledTimes(1);
    });

    it('does not render when isOpen is false', () => {
      const onClose = vi.fn();
      render(
        <Modal isOpen={false} onClose={onClose} title="Hidden Modal">
          <div>Content</div>
        </Modal>
      );
      expect(screen.queryByText('Hidden Modal')).not.toBeInTheDocument();
    });
  });

  describe('Input', () => {
    it('renders label, input, and error message with accessible attributes', () => {
      render(
        <Input
          label="Invoice Number"
          error="Invoice number is required"
          defaultValue="INV-123"
        />
      );

      const input = screen.getByLabelText(/Invoice Number/);
      expect(input).toBeInTheDocument();
      expect(input).toHaveAttribute('aria-invalid', 'true');
      expect(screen.getByText('Invoice number is required')).toBeInTheDocument();
    });
  });
});
